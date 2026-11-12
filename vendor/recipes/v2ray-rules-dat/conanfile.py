from conan import ConanFile
from conan.tools.layout import basic_layout
from conan.tools.files import download, copy

import os

class V2rayRulesDat(ConanFile):
    name = "v2ray-rules-dat"
    version = "202603162227"

    def layout(self):
        basic_layout(self, build_folder=".")

    def source(self):
        copy(self, "*.dat", src=os.path.join(os.environ["AMNEZIA_DEPS_DIR"], "src", "v2ray-rules-dat"), dst=self.source_folder)

    def package(self):
        copy(self, "*.dat", src=self.build_folder, dst=self.package_folder)

    def package_info(self):
        self.cpp_info.set_property("cmake_target_name", "Loyalsoldier::v2ray-rules-dat")
        self.cpp_info.set_property("cmake_extra_variables", {
            "GEOSITE_DAT_PATH": os.path.join(self.package_folder, "geosite.dat").replace("\\", "/"),
            "GEOIP_DAT_PATH": os.path.join(self.package_folder, "geoip.dat").replace("\\", "/")
        })
