from owrx.map import Map, LatLngLocation
from owrx.aprs import getSymbolData
from owrx.storage import Storage
from owrx.config import Config
from csdr.module import ThreadModule
from pycsdr.types import Format
from datetime import datetime
import pickle
import os
import re
import json

import logging

logger = logging.getLogger(__name__)


class TextParser(ThreadModule):
    def __init__(self, filePrefix: str = "LOG", service: bool = False):
        # Use these colors to label messages by address
        self.colors = [
            "#FFFFFF", "#999999", "#FF9999", "#FFCC99", "#FFFF99", "#CCFF99",
            "#99FF99", "#99FFCC", "#99FFFF", "#99CCFF", "#9999FF", "#CC99FF",
            "#FF99FF", "#FF99CC",
        ]
        self.service   = service
        self.frequency = 0
        self.data      = bytearray(b'')
        self.filePfx   = filePrefix
        self.file      = None
        self.maxLines  = 10000
        self.cntLines  = 0
        self.colorBuf  = {}
        super().__init__()

    def __del__(self):
        # Close currently open file, if any
        self.closeFile()

    def closeFile(self):
        if self.file is not None:
            try:
                logger.debug("Closing log file '%s'." % self.fileName)
                self.file.close()
                self.file = None
                # Delete excessive files from storage
                logger.debug("Performing storage cleanup...")
                Storage().cleanStoredFiles()

            except Exception as exptn:
                logger.debug("Exception closing file: %s" % str(exptn))
                self.file = None

    def newFile(self, fileName):
        self.closeFile()
        try:
            self.fileName = Storage().getFilePath(fileName + ".txt")
            logger.debug("Opening log file '%s'..." % self.fileName)
            self.file = open(self.fileName, "wb")
            self.cntLines = 0

        except Exception as exptn:
            logger.debug("Exception opening file: %s" % str(exptn))
            self.file = None

    def writeFile(self, data):
        # If no file open, create and open a new file
        if self.file is None:
            self.newFile(Storage().makeFileName(self.filePfx+"-{0}", self.frequency))
        # If file open now...
        if self.file is not None:
            # Write new line into the file
            try:
                self.file.write(data)
            except Exception:
                pass
            # No more than maxLines per file
            self.cntLines = self.cntLines + 1
            if self.cntLines >= self.maxLines:
                self.closeFile()

    def getInputFormat(self) -> Format:
        return Format.CHAR

    def getOutputFormat(self) -> Format:
        return Format.CHAR

    def setDialFrequency(self, frequency: int) -> None:
        self.frequency = frequency

    # Compose name of this decoder, made of client/service and frequency
    def myName(self):
        return "%s%s" % (
            "Service" if self.service else "Client",
            " at %dkHz" % (self.frequency // 1000) if self.frequency>0 else ""
        )

    # Get current UTC time in a standardized format
    def getUtcTime(self) -> str:
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    # Get a unique color for a given ID, reusing colors as we go
    def getColor(self, id: str) -> str:
        if id in self.colorBuf:
            # Sort entries in order of freshness
            color = self.colorBuf.pop(id)
        elif len(self.colorBuf) < len(self.colors):
            # Assign each initial entry color based on its order
            color = self.colors[len(self.colorBuf)]
        else:
            # If we run out of colors, reuse the oldest entry
            color = self.colorBuf.pop(next(iter(self.colorBuf)))
        # Done
        self.colorBuf[id] = color
        return color

    # DERIVED CLASSES SHOULD IMPLEMENT THIS FUNCTION!
    def parse(self, msg: str):
        # By default, do not parse, just return the string
        return msg

    # ONLY IMPLEMENT THIS FUNCTION WHEN REPORTING LOCATION FROM SERVICE!
    def updateLocation(self, msg: str):
        # By default, do nothing
        pass

    def run(self):
        logger.debug("%s starting..." % self.myName())
        # Run while there is input data
        while self.doRun:
            # Read input data
            inp = self.reader.read()
            # Terminate if no input data
            if inp is None:
                logger.debug("%s exiting..." % self.myName())
                self.doRun = False
                break
            # Add read data to the buffer
            self.data = self.data + inp.tobytes()
            # Process buffer contents
            out = self.process()
            # Keep processing while there is input to parse
            while out is not None:
                if len(out)>0:
                    if isinstance(out, bytes):
                        self.writer.write(out)
                    elif isinstance(out, str):
                        self.writer.write(bytes(out, 'utf-8'))
                    else:
                        self.writer.write(pickle.dumps(out))
                out = self.process()

    def process(self):
        # No result yet
        out = None

        # Search for end-of-line
        eol = self.data.find(b'\n')

        # If found end-of-line...
        if eol>=0:
            try:
                msg = self.data[0:eol].decode(encoding="utf-8", errors="replace")
                logger.debug("%s: %s" % (self.myName(), msg))
                # If running as a service...
                if self.service:
                    # Write message into open log file, including end-of-line
                    self.writeFile(self.data[0:eol+1])
                    # Optionally, parse and report location
                    self.updateLocation(msg)
                    # Empty result
                    out = {}
                else:
                    # Let parse() function do its thing
                    out = self.parse(msg)

            except Exception as exptn:
                logger.debug("%s: Exception parsing: %s" % (self.myName(), str(exptn)))

            # Remove parsed message from input, including end-of-line
            del self.data[0:eol+1]

        # Return parsed result or None if no result yet
        return out


class IsmParser(TextParser):
    def __init__(self, service: bool = False):
        super().__init__(filePrefix="ISM", service=service)

    def parse(self, msg: str):
        # Expect JSON data in text form
        out = json.loads(msg)
        # Add mode name and a color to identify the sender
        out["mode"]  = "ISM"
        out["color"] = self.getColor(out["id"])
        return out


class PageParser(TextParser):
    def __init__(self, service: bool = False):
        # When true, try filtering out unreadable messages
        pm = Config.get()
        self.filtering = "paging_filter" in pm and pm["paging_filter"]
        # POCSAG<baud>: Address: <num> Function: <hex> (Certainty: <num> )?(Numeric|Alpha|Skyper): <message>
        self.rePocsag = re.compile(r"POCSAG(\d+):\s*Address:\s*(\S+)\s+Function:\s*(\S+)(\s+Certainty:.*(\d+))?(\s+(\S+):\s*(.*))?")
        # FLEX|NNNN-NN-NN NN:NN:NN|<baud>/<value>/C/C|NN.NNN|NNNNNNNNN|<type>|<message>
        # FLEX|NNNN-NN-NN NN:NN:NN|<baud>/<value>/C/C|NN.NNN|NNNNNNNNN NNNNNNNNN|<type>|<message>
        self.reFlex1 = re.compile(r"FLEX\|(\d\d\d\d-\d\d-\d\d\s+\d\d:\d\d:\d\d)\|(\d+/\d+/\S/\S)\|(\d\d\.\d\d\d)\|(\d+(?:\s+\d+)?)\|(\S+)\|(.*)")
        # FLEX: NNNN-NN-NN NN:NN:NN <baud>/<value>/C NN.NNN [NNNNNNNNN] <type> <message>
        self.reFlex2 = re.compile(r"FLEX:\s+(\d\d\d\d-\d\d-\d\d\s+\d\d:\d\d:\d\d)\s+(\d+/\d+/\S)\s+(\d\d\.\d\d\d)\s+\[(\d+)\]\s+(\S+)\s+(.*)")
        # FLEX message status
        self.reFlex3 = re.compile(r"(\d+/\d+)(/\S)?/\S")
        # Message filtering patterns
        self.reControl = re.compile(r"<[\w\d]{2,3}>")
        self.reSpaces = re.compile(r"[\000-\037\s]+")
        # Fragmented messages will be assembled here
        self.flexBuf = {}
        # Construct parent object
        super().__init__(filePrefix="PAGE", service=service)

    def parse(self, msg: str):
        # Steer message to POCSAG or FLEX parser
        if msg.startswith("POCSAG"):
            return self.parsePocsag(msg)
        elif msg.startswith("FLEX"):
            return self.parseFlex(msg)
        else:
            return {}

    def collapseSpaces(self, msg: str) -> str:
        # Collapse white space
        return self.reSpaces.sub(" ", msg).strip()

    def isReadable(self, msg: str) -> bool:
       # Consider string human-readable if the average word length
       # is sufficiently small
       spaces  = msg.count(" ")
       letters = len(msg) - spaces
       return (letters > 0) and (letters / (spaces+1) < 40)

    def parsePocsag(self, msg: str):
        # No result yet
        out = {}

        # Parse POCSAG messages
        r = self.rePocsag.match(msg)
        if r is not None:
            baud      = r.group(1)
            capcode   = r.group(2)
            function  = r.group(3)
            certainty = r.group(5)
            msgtype   = "" if not r.group(7) else r.group(7)
            msg       = "" if not r.group(8) else r.group(8)

            # Remove POCSAG "<XXX>" sequences and collapse white space
            msg = self.collapseSpaces(self.reControl.sub(" ", msg))

            # When filtering, only output readable messages
            if not self.filtering or (msgtype=="Alpha" and len(msg)>0):
                out = {
                    "mode":      "POCSAG",
                    "baud":      baud,
                    "timestamp": self.getUtcTime(),
                    "address":   capcode,
                    "function":  function,
                    "certainty": certainty,
                    "color":     self.getColor(capcode),
                    "type":      msgtype,
                    "message":   msg
                }
                # Output type and message
                if len(msgtype)>0:
                    out["type"] = msgtype
                if len(msg)>0:
                    out["message"] = msg

        # Done
        return out

    def parseFlex(self, msg: str):
        # No result yet
        out = {}

        # Parse FLEX messages
        r = self.reFlex1.match(msg)
        r = self.reFlex2.match(msg) if not r else r
        if r is not None:
            tstamp  = r.group(1)
            state   = r.group(2)
            frame   = r.group(3)
            capcode = r.group(4)
            msgtype = r.group(5)
            msg     = r.group(6)
            rm      = self.reFlex3.match(state)
            baud    = "" if not rm else rm.group(1)
            frag    = "" if not rm or not rm.group(2) else rm.group(2)[1]
            # Assemble fragmented messages in flexBuf
            if frag == "F" or frag == "C":
                # Do not let flexBuf grow too much
                if len(self.flexBuf)>1024:
                    self.flexBuf = {}
                # Accumulate messages in flexBuf, index by capcode
                if capcode in self.flexBuf:
                    self.flexBuf[capcode] += msg
                else:
                    self.flexBuf[capcode] = msg
            # Only output message once it completes
            if frag == "F":
                msg = ""
            elif frag == "C":
                msg = self.flexBuf[capcode]
                del self.flexBuf[capcode]
            # Do not report fragments of messages
            if frag != "F":
                # Collapse white space
                msg = self.collapseSpaces(msg)
                # When filtering, only output readable messages
                if not self.filtering or (msgtype=="ALN" and self.isReadable(msg)):
                    out = {
                        "mode":      "FLEX",
                        "baud":      baud,
                        "timestamp": tstamp,
                        "state":     state,
                        "frame":     frame,
                        "address":   capcode,
                        "color":     self.getColor(capcode),
                        "type":      msgtype
                    }
                    # Output message
                    if len(msg)>0:
                        out["message"] = msg

        # Done
        return out


class SelCallParser(TextParser):
    def __init__(self, service: bool = False):
        self.reSplit = re.compile(r"(ZVEI1|ZVEI2|ZVEI3|DZVEI|PZVEI|DTMF|EEA|EIA|CCIR):\s+")
        self.reMatch = re.compile(r"ZVEI1|ZVEI2|ZVEI3|DZVEI|PZVEI|DTMF|EEA|EIA|CCIR")
        self.mode = ""
        # Construct parent object
        super().__init__(filePrefix="SELCALL", service=service)

    def parse(self, msg: str):
        # Parse SELCALL messages
        dec = None
        out = ""
        r = self.reSplit.split(msg)

        for s in r:
            if self.reMatch.match(s):
                dec = s
            elif dec is not None and len(s)>0:
                if dec != self.mode:
                    out += "[" + dec + "] "
                    self.mode = dec
                out += s + " "
                dec = None
        # Done
        return out


class HfdlLocation(LatLngLocation):
    def __init__(self, data):
        super().__init__(data["lat"], data["lon"])
        self.data = data

    def __dict__(self):
        res = super(HfdlLocation, self).__dict__()
        res["symbol"] = getSymbolData('^', '/')
        if "aircraft" in self.data:
            res["aircraft"] = self.data["aircraft"]
        if "message" in self.data:
            res["comment"] = self.data["message"]
        return res


class HfdlParser(TextParser):
    def __init__(self, service: bool = False):
        super().__init__(filePrefix="HFDL", service=service)

    def parse(self, msg: str):
        # Expect JSON data in text form
        data   = json.loads(msg)
        tstamp = datetime.fromtimestamp(data["hfdl"]["t"]["sec"]).strftime("%I:%M:%S")
        # @@@ Only parse messages that have LDPU frames for now !!!
        if "lpdu" not in data["hfdl"]:
            return {}
        # Collect basic data first
        out = {
            "mode": "HFDL",
            "time": tstamp,
        }
        # Parse LPDU if present
        if "lpdu" in data["hfdl"]:
            self.parseLpdu(data["hfdl"]["lpdu"], out)
        # Parse SPDU if present
        if "spdu" in data["hfdl"]:
            self.parseSpdu(data["hfdl"]["spdu"], out)
        # Parse MPDU if present
        if "mpdu" in data["hfdl"]:
            self.parseMpdu(data["hfdl"]["mpdu"], out)
        # Done
        return out

    def parseSpdu(self, data, out):
        # Not parsing yet
        out["type"] = "SPDU frame"
        return out

    def parseMpdu(self, data, out):
        # Not parsing yet
        out["type"] = "MPDU frame"
        return out

    def parseLpdu(self, data, out):
        # Collect data
        out["type"] = data["type"]["name"]
        # Add aircraft info, if present
        if "ac_info" in data and "icao" in data["ac_info"]:
            out["aircraft"] = data["ac_info"]["icao"].strip()
        # Source might be a ground station
        if data["src"]["type"] == "Ground station":
            out["flight"] = "GS-%d" % data["src"]["id"]
        # Parse HFNPDU is present
        if "hfnpdu" in data:
            self.parseHfnpdu(data["hfnpdu"], out)
        # Done
        return out

    def parseHfnpdu(self, data, out):
        # If we see ACARS message, parse it and drop out
        if "acars" in data:
            return self.parseAcars(data["acars"], out)
        # Use flight ID as unique identifier
        flight = data["flight_id"].strip() if "flight_id" in data else ""
        if len(flight)>0:
            out["flight"] = flight
            out["color"]  = self.getColor(flight)
        # If message carries time, parse it
        if "utc_time" in data:
            msgtime = data["utc_time"]
        elif "time" in data:
            msgtime = data["time"]
        else:
            msgtime = None
        # Add reported message time, if present
        if msgtime:
            out["msgtime"] = "%02d:%02d:%02d" % (
                msgtime["hour"], msgtime["min"], msgtime["sec"]
            )
        # Add aircraft location, if present
        if "pos" in data:
            out["lat"] = data["pos"]["lat"]
            out["lon"] = data["pos"]["lon"]
            # Report location on the map
            self.updateMap(out)
        # Done
        return out

    def parseAcars(self, data, out):
        # Collect data
        out["type"]     = "ACARS frame"
        out["aircraft"] = data["reg"].strip()
        out["message"]  = data["msg_text"].strip()
        # Use flight ID as unique identifier
        flight = data["flight"].strip() if "flight" in data else ""
        if len(flight)>0:
            out["flight"] = flight
            out["color"]  = self.getColor(flight)
        # Done
        return out

    def updateMap(self, data):
        if "flight" in data and "lat" in data and "lon" in data:
            loc = HfdlLocation(data)
            Map.getSharedInstance().updateLocation(data["flight"], loc, data["mode"])
