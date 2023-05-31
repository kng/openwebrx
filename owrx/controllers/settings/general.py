from owrx.controllers.settings import SettingsFormController
from owrx.form.section import Section
from owrx.config.core import CoreConfig
from owrx.form.input import (
    TextInput,
    NumberInput,
    FloatInput,
    TextAreaInput,
    DropdownInput,
    CheckboxInput,
    Option,
)
from owrx.form.input.validator import RangeValidator
from owrx.form.input.converter import WaterfallColorsConverter, IntConverter
from owrx.form.input.receiverid import ReceiverKeysConverter
from owrx.form.input.gfx import AvatarInput, TopPhotoInput
from owrx.form.input.device import WaterfallLevelsInput, WaterfallAutoLevelsInput
from owrx.form.input.location import LocationInput
from owrx.waterfall import WaterfallOptions
from owrx.breadcrumb import Breadcrumb, BreadcrumbItem
from owrx.controllers.settings import SettingsBreadcrumb
import shutil
import os
import re
from glob import glob

import logging

logger = logging.getLogger(__name__)


class GeneralSettingsController(SettingsFormController):
    def getTitle(self):
        return "General Settings"

    def get_breadcrumb(self) -> Breadcrumb:
        return SettingsBreadcrumb().append(BreadcrumbItem("General Settings", "settings/general"))

    def getSections(self):
        return [
            Section(
                "Receiver information",
                TextInput("receiver_name", "Receiver name"),
                TextInput("receiver_location", "Receiver location"),
                NumberInput(
                    "receiver_asl",
                    "Receiver elevation",
                    append="meters above mean sea level",
                ),
                TextInput("receiver_admin", "Receiver admin"),
                LocationInput("receiver_gps", "Receiver coordinates"),
                TextInput("photo_title", "Photo title"),
                TextAreaInput("photo_desc", "Photo description", infotext="HTML supported "),
            ),
            Section(
                "Receiver images",
                AvatarInput(
                    "receiver_avatar",
                    "Receiver Avatar",
                    infotext="For performance reasons, images are cached. "
                    + "It can take a few hours until they appear on the site.",
                ),
                TopPhotoInput(
                    "receiver_top_photo",
                    "Receiver Panorama",
                    infotext="For performance reasons, images are cached. "
                    + "It can take a few hours until they appear on the site.",
                ),
            ),
            Section(
                "Receiver limits",
                NumberInput(
                    "max_clients",
                    "Maximum number of clients",
                    infotext="Number of people who can connect at the same time.",
                ),
                NumberInput(
                    "keep_files",
                    "Maximum number of files",
                    infotext="Number of received images and other files to keep.",
                ),
                NumberInput(
                    "session_timeout",
                    "Session timeout",
                    infotext="Client session timeout in seconds (0 to disable timeout).",
                    append="secs",
                ),
                TextInput(
                    "usage_policy_url",
                    "Usage policy URL",
                    infotext="Specifies web page describing receiver usage policy "
                    + "and shown when a client session times out.",
                ),
                CheckboxInput(
                    "allow_audio_recording",
                    "Allow users to record received audio",
                ),
                CheckboxInput(
                    "allow_center_freq_changes",
                    "Allow users to change center frequency",
                ),
                TextInput(
                    "magic_key",
                    "Magic key",
                    infotext="Enter a key the user has to supply to change center frequency."
                    + " Leave empty if you do not want to protect frequency changes with a key."
                    + " When enabled, the key has to be added to receiver's URL after the hash"
                    + " sign: http://my.receiver.com/#key=keyvalue.",
                ),
            ),
            Section(
                "Receiver listings",
                TextAreaInput(
                    "receiver_keys",
                    "Receiver keys",
                    converter=ReceiverKeysConverter(),
                    infotext="Put the keys you receive on listing sites (e.g. "
                    + '<a href="https://www.receiverbook.de" target="_blank">Receiverbook</a>) here, one per line',
                ),
            ),
            Section(
                "Waterfall settings",
                DropdownInput(
                    "waterfall_scheme",
                    "Waterfall color scheme",
                    options=WaterfallOptions,
                ),
                TextAreaInput(
                    "waterfall_colors",
                    "Custom waterfall colors",
                    infotext="Please provide 6-digit hexadecimal RGB colors in HTML notation (#RRGGBB)"
                    + " or HEX notation (0xRRGGBB), one per line",
                    converter=WaterfallColorsConverter(),
                ),
                NumberInput(
                    "fft_fps",
                    "FFT speed",
                    infotext="This setting specifies how many lines are being added to the waterfall per second. "
                    + "Higher values will give you a faster waterfall, but will also use more CPU.",
                    append="frames per second",
                ),
                NumberInput("fft_size", "FFT size", append="bins"),
                FloatInput(
                    "fft_voverlap_factor",
                    "FFT vertical overlap factor",
                    infotext="If fft_voverlap_factor is above 0, multiple FFTs will be used for creating a line on the "
                    + "diagram.",
                ),
                WaterfallLevelsInput("waterfall_levels", "Waterfall levels"),
                WaterfallAutoLevelsInput(
                    "waterfall_auto_levels",
                    "Automatic adjustment margins",
                    infotext="Specifies the upper and lower dynamic headroom that should be added when automatically "
                    + "adjusting waterfall colors",
                ),
                NumberInput(
                    "waterfall_auto_min_range",
                    "Automatic adjustment minimum range",
                    append="dB",
                    infotext="Minimum dynamic range the waterfall should cover after automatically adjusting "
                    + "waterfall colors",
                ),
            ),
            Section(
                "Compression",
                DropdownInput(
                    "audio_compression",
                    "Audio compression",
                    options=[
                        Option("adpcm", "ADPCM"),
                        Option("none", "None"),
                    ],
                ),
                DropdownInput(
                    "fft_compression",
                    "Waterfall compression",
                    options=[
                        Option("adpcm", "ADPCM"),
                        Option("none", "None"),
                    ],
                ),
            ),
            Section(
                "Display settings",
                NumberInput(
                    "ui_opacity",
                    "User interface opacity",
                    infotext="Specifies how opaque user interface is, "
                    + "10% for near invisible, 100% for totally solid.",
                    validator=RangeValidator(10, 100),
                    append="%",
                ),
                CheckboxInput(
                    "ui_frame",
                    "Show frame around receiver panel",
                ),
                DropdownInput(
                    "tuning_precision",
                    "Tuning precision",
                    options=[Option(str(i), "{} Hz".format(10 ** i)) for i in range(0, 6)],
                    converter=IntConverter(),
                ),
            ),
            Section(
                "Map settings",
                TextInput(
                    "google_maps_api_key",
                    "Google Maps API key",
                    infotext="Google Maps requires an API key, check out "
                    + '<a href="https://developers.google.com/maps/documentation/embed/get-api-key" target="_blank">'
                    + "their documentation</a> on how to obtain one.",
                ),
                NumberInput(
                    "map_position_retention_time",
                    "Map retention time",
                    infotext="Specifies how log markers / grids will remain visible on the map",
                    append="s",
                ),
                CheckboxInput(
                    "map_ignore_indirect_reports",
                    "Ignore position reports arriving via indirect path",
                ),
                CheckboxInput(
                    "map_prefer_recent_reports",
                    "Prefer more recent position reports to shorter path reports",
                ),
                TextInput(
                    "callsign_url",
                    "Callsign database URL",
                    infotext="Specifies callsign lookup URL, such as QRZ.COM "
                    + "or QRZCQ.COM. Place curly brackers ({}) where callsign "
                    + "is supposed to be.",
                ),
                TextInput(
                    "vessel_url",
                    "Vessel database URL",
                    infotext="Specifies vessel lookup URL, such as VESSELFINDER.COM, "
                    + "allowing to look up vessel information by its AIS MMSI number. "
                    + "Place curly brackers ({}) where MMSI is supposed to be.",
                ),
                TextInput(
                    "aircraft_url",
                    "Aircraft database URL",
                    infotext="Specifies aircraft lookup URL, such as PLAINSPOTTERS.NET, "
                    + "allowing to look up aircraft information by its registration number "
                    + "or ICAO MODE-S code. Place curly brackers ({}) where the aircraft "
                    + "identifier is supposed to be.",
                ),
                TextInput(
                    "flight_url",
                    "Flight database URL",
                    infotext="Specifies flight lookup URL, such as FLIGHTAWARE.COM, "
                    + "allowing to look up aircraft flights. Place curly brackers ({}) "
                    + "where flight identifier is supposed to be.",
                ),
            ),
        ]

    def remove_existing_image(self, image_id):
        config = CoreConfig()
        # remove all possible file extensions
        for ext in ["png", "jpg", "webp"]:
            try:
                os.unlink("{}/{}.{}".format(config.get_data_directory(), image_id, ext))
            except FileNotFoundError:
                pass

    def handle_image(self, data, image_id):
        if image_id in data:
            config = CoreConfig()
            if data[image_id] == "restore":
                self.remove_existing_image(image_id)
            elif data[image_id]:
                if not data[image_id].startswith(image_id):
                    logger.warning("invalid file name: %s", data[image_id])
                else:
                    # get file extension (at least 3 characters)
                    # should be all lowercase since they are set by the upload script
                    pattern = re.compile(".*\\.([a-z]{3,})$")
                    matches = pattern.match(data[image_id])
                    if matches is None:
                        logger.warning("could not determine file extension for %s", image_id)
                    else:
                        self.remove_existing_image(image_id)
                        ext = matches.group(1)
                        data_file = "{}/{}.{}".format(config.get_data_directory(), image_id, ext)
                        temporary_file = "{}/{}".format(config.get_temporary_directory(), data[image_id])
                        shutil.copy(temporary_file, data_file)
            del data[image_id]
            # remove any accumulated temporary files on save
            for file in glob("{}/{}*".format(config.get_temporary_directory(), image_id)):
                os.unlink(file)

    def processData(self, data):
        # Image handling
        for img in ["receiver_avatar", "receiver_top_photo"]:
            self.handle_image(data, img)
        # special handling for waterfall colors: custom colors only stay in config if custom color scheme is selected
        if "waterfall_scheme" in data:
            scheme = WaterfallOptions(data["waterfall_scheme"])
            if scheme is not WaterfallOptions.CUSTOM and "waterfall_colors" in data:
                data["waterfall_colors"] = None
        super().processData(data)
