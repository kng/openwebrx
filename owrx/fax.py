from owrx.storage import Storage
from csdr.module import ThreadModule
from pycsdr.types import Format
from datetime import datetime
import base64
import pickle
import os

import logging

logger = logging.getLogger(__name__)

class FaxParser(ThreadModule):
    def __init__(self, service: bool = False):
        self.service   = service
        self.frequency = 0
        self.file      = None
        self.data      = bytearray(b'')
        self.width     = 0
        self.height    = 0
        self.depth     = 0
        self.line      = 0
        self.ioc       = 0
        self.lpm       = 0
        self.colors    = None
        super().__init__()

    def __del__(self):
        # Close currently open file, if any
        self.closeFile()

    def closeFile(self):
        if self.file is not None:
            try:
                logger.debug("Closing bitmap file '%s'." % self.fileName)
                self.file.close()
                self.file = None
                if self.height==0 or self.line<self.height:
                    logger.debug("Deleting short bitmap file '%s'." % self.fileName)
                    os.unlink(self.fileName)
                else:
                    # Convert file from BMP to PNG
                    logger.debug("Converting '%s' to PNG..." % self.fileName)
                    Storage().convertImage(self.fileName)
                    # Delete excessive files from storage
                    logger.debug("Performing storage cleanup...")
                    Storage().cleanStoredFiles()

            except Exception as e:
                logger.debug("Exception closing file: %s" % str(e))
                self.file = None

    def newFile(self, fileName):
        self.closeFile()
        try:
            self.fileName = Storage().getFilePath(fileName + ".bmp")
            logger.debug("Opening bitmap file '%s'..." % self.fileName)
            self.file = open(self.fileName, "wb")

        except Exception as e:
            logger.debug("Exception opening file: %s" % str(e))
            self.file = None

    def writeFile(self, data):
        if self.file is not None:
            try:
                self.file.write(data)
            except Exception:
                pass

    def getInputFormat(self) -> Format:
        return Format.CHAR

    def getOutputFormat(self) -> Format:
        return Format.CHAR

    def setDialFrequency(self, frequency: int) -> None:
        self.frequency = frequency

    def myName(self) -> str:
        return "%s%s" % (
            "Service" if self.service else "Client",
            " at %dkHz" % (self.frequency // 1000) if self.frequency>0 else ""
        )

    def applyRLE(self, buf):
        out = b''
        j = 0
        k = 0
        while j<len(buf):
            # Search for the next non-repeating byte
            i = j + 1
            while i<len(buf) and buf[i]==buf[j]:
                i = i + 1
            # If got two or more repeating bytes...
            if i-j>=2:
                # Add non-repeating bytes
                while k<j:
                    n = min(j-k, 128)
                    out += bytes([n - 1])
                    out += buf[k : k+n]
                    k += n
                # Add repeating bytes
                while k<i:
                    n = min(i-k, 129)
                    out += bytes([n + 128 - 2, buf[j]])
                    k += n
            # Update current position
            j = i
        # Add remaining non-repeating bytes
        while k<j:
            n = min(j-k, 128)
            out += bytes([n - 1])
            out += buf[k : k+n]
            k += n
        # Done
        return out

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
                    self.writer.write(pickle.dumps(out))
                out = self.process()

    def process(self):
        # No result yet
        out = None

        try:
            # Pixel size, line width in pixels and bytes
            b = self.depth / 8 if self.depth>8 else 1
            w = self.width
            l = w * b

            # Search for BMP header and comments first, in case
            # previous bitmap terminates early
            ll = min(l, len(self.data)) if l>0 else len(self.data)
            ph = self.data[0:ll].find(b'BM')
            pc = self.data[0:ll].find(b' [')

            #
            # If comment found, and we are not receiving an image...
            #
            if pc>=0 and (ph<0 or pc<ph) and l==0:
                # Skip everything until ' ['
                del self.data[0:pc]
                # Look for the closing bracket
                pc = self.data[0:ll].find(b']')
                if pc>=0:
                    # Extract message contents
                    msg = self.data[2:pc].decode()
                    # Remove parsed data
                    del self.data[0:pc+1]
                    # Log message
                    logger.debug("%s says [%s]" % (self.myName(), msg))
                    # If running as a service...
                    if self.service:
                        # Empty result
                        out = {}
                    else:
                        # Compose result
                        out = {
                            "mode":      "Fax",
                            "message":   msg,
                            "frequency": self.frequency
                        }

            #
            # If BMP header ('BM ... <40> ...') found...
            #
            elif ph>=0 and ph+14<ll and self.data[ph+14]==40:
                # Skip everything until 'BM'
                del self.data[0:ph]
                # If got the entire header...
                if len(self.data)>=54+4*256:
                    self.width  = self.data[18] + (self.data[19]<<8) + (self.data[20]<<16) + (self.data[21]<<24)
                    self.height = self.data[22] + (self.data[23]<<8) + (self.data[24]<<16) + (self.data[25]<<24)
                    self.depth  = self.data[28] + (self.data[29]<<8)
                    # BMP height value is negative
                    self.height = 0x100000000 - self.height
                    # Fax mode is passed via reserved area at offset 6
                    self.ioc    = self.data[6] * 4
                    self.lpm    = self.data[7]
                    self.line   = 0
                    # Find total header size
                    headerSize = 54 + (4*256 if self.depth==8 else 0)
                    # 256x4 palette follows the header
                    if headerSize>54:
                        self.colors = self.data[54:headerSize]
                    else:
                        self.colors = None
                    # Find mode name and time
                    modeName  = "IOC-%d %dLPM" % (self.ioc, self.lpm)
                    timeStamp = datetime.utcnow().strftime("%H:%M:%S")
                    fileName  = Storage().makeFileName("FAX-{0}", self.frequency)
                    logger.debug("%s receiving %dx%d %s frame as '%s'." % (
                        self.myName(), self.width, self.height,
                        modeName, fileName
                    ))
                    # If running as a service...
                    if self.service:
                        # Create a new image file and write BMP header
                        self.newFile(fileName)
                        self.writeFile(self.data[0:headerSize])
                        # Empty result
                        out = {}
                    else:
                        # Compose result
                        out = {
                            "mode":      "Fax",
                            "width":     self.width,
                            "height":    self.height,
                            "depth":     self.depth,
                            "faxMode":   modeName,
                            "timestamp": timeStamp,
                            "filename":  fileName,
                            "frequency": self.frequency
                        }
                    # Remove parsed data
                    del self.data[0:headerSize]

            #
            # If currently receiving image...
            #
            elif l>0:
                if len(self.data)>=l:
                    #logger.debug("%s got line %d of %d/%d pixels" % (
                    #    self.myName(), self.line, w, len(self.data)/b
                    #))
                    # Advance scanline
                    self.line = self.line + 1
                    # If running as a service...
                    if self.service:
                        # Write a scanline into open image file
                        self.writeFile(self.data[0:l])
                        # Close once the last scanline reached
                        if self.line>=self.height:
                            self.closeFile()
                        # Empty result
                        out = {}
                    else:
                        # Compose result
                        #rle = self.applyRLE(self.data[0:l])
                        out = {
                            "mode":   "Fax",
                            "line":   self.line-1,
                            "width":  self.width,
                            "height": self.height,
                            "depth":  self.depth,
                            "rle":    False,
                            "pixels": base64.b64encode(self.data[0:l]).decode(),
                        }
                    # If we reached the end of frame, finish scan
                    if self.line>=self.height:
                        self.width  = 0
                        self.height = 0
                        self.depth  = 0
                        self.line   = 0
                        self.ioc    = 0
                        self.lpm    = 0
                        self.colors = None
                    # Remove parsed data
                    del self.data[0:l]

            #
            # If not receiving anything...
            #
            else:
                # Skip all data, but leave some since we may have 'BM ...'
                l = ph if ph>=0 and ph+14>=len(self.data) else len(self.data)-1
                del self.data[0:l]

        except Exception as e:
            logger.debug("%s: Exception parsing: %s" % (self.myName(), str(e)))

        # Return parsed result or None if no result yet
        return out

