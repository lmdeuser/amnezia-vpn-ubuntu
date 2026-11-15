import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import obs_controller as oc
from tools import update_obs as uo

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def test_packaging_digest_ignores_changelog_and_tracks_patches(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            shutil.copytree(ROOT / "debian", repo / "debian")
            shutil.copytree(ROOT / "obs", repo / "obs")
            shutil.copytree(ROOT / "vendor", repo / "vendor")

            baseline = uo.packaging_digest(repo)
            (repo / "debian/changelog").write_text("changed changelog\n")
            (repo / "debian/client-config.env").write_text("export FOO=bar\n")
            self.assertEqual(uo.packaging_digest(repo), baseline)

            (repo / "debian/preinst").write_text("#!/bin/sh\nset -e\n")
            self.assertNotEqual(uo.packaging_digest(repo), baseline)

    def test_next_obs_revision_and_monotonic_version_guard(self):
        uv = "5.1.1.4+git20261114.5c732f6edc70"
        self.assertEqual(uo.next_obs_revision(uv, []), 1)
        self.assertEqual(uo.next_obs_revision(uv, [f"{uv}-0ubuntu1~obs1"]), 2)
        self.assertEqual(uo.next_obs_revision(uv, [f"{uv}-0ubuntu1~obs1", f"{uv}-0ubuntu1~obs3"]), 4)

        uo.ensure_version_monotonic(f"{uv}-0ubuntu1~obs2", f"{uv}-0ubuntu1~obs1")
        with self.assertRaises(RuntimeError):
            uo.ensure_version_monotonic(
                "5.1.1.4+git20261115.1111bbbbbbbb-0ubuntu1~obs1",
                "5.1.1.4+git20261115.9999aaaaaaaa-0ubuntu1~obs1",
            )

    def test_validate_debian_patches_applies_series_and_detects_conflicts(self):
        with TemporaryDirectory() as tmp:
            upstream = Path(tmp) / "upstream"
            tests_dir = upstream / "client/tests"
            tests_dir.mkdir(parents=True)

            model_cpp = tests_dir / "testXrayConfigModel.cpp"
            model_lines = [f"// line {i}" for i in range(1, 320)]
            model_lines[170] = "                      issued(baseConfig(flowCase ? \"raw\" : \"xhttp\", \"reality\", flowCase ? \"xtls-rprx-vision\" : \"\")));"
            model_lines[171] = ""
            model_lines[172] = "    if (edit == QLatin1String(\"fingerprint\"))"
            model_lines[173] = "        model.setFingerprint(\"firefox\");"
            model_lines[174] = "    else if (edit == QLatin1String(\"method\"))"
            model_lines[175] = "        model.setXhttpUplinkMethod(\"PATCH\");"
            model_lines[176] = "    else if (edit == QLatin1String(\"chunk\"))"
            model_lines[275] = "{"
            model_lines[276] = "    XrayConfigModel model;"
            model_lines[277] = "    model.updateModel(DockerContainer::Xray, issued(baseConfig(\"xhttp\", \"reality\", \"\")));"
            model_lines[278] = "    model.setFingerprint(\"firefox\");"
            model_lines[279] = "    model.setXhttpUplinkMethod(\"PATCH\");"
            model_lines[280] = ""
            model_lines[281] = "    const XrayProtocolConfig saved = model.getProtocolConfig();"
            model_lines[282] = "    QVERIFY(saved.hasClientConfig());"
            model_lines[283] = "    const QJsonObject native = QJsonDocument::fromJson(saved.clientConfig->nativeConfig.toUtf8()).object();"
            model_lines[284] = "    const QJsonObject stream = streamOf(vlessOutbound(native));"
            model_lines[285] = "    QCOMPARE(stream.value(\"realitySettings\").toObject().value(\"fingerprint\").toString(), QStringLiteral(\"firefox\"));"
            model_lines[286] = "    QCOMPARE(stream.value(\"xhttpSettings\").toObject().value(\"uplinkHTTPMethod\").toString(), QStringLiteral(\"PATCH\"));"
            model_lines[287] = "    QCOMPARE(stream.value(\"realitySettings\").toObject().value(\"publicKey\").toString(), key32('\\x02'));"
            model_lines[288] = "    QCOMPARE(saved.clientConfig->id, clientId());"
            model_lines[293] = "    XrayConfigModel model;"
            model_lines[294] = "    const QString broken = QStringLiteral(R\"({\"outbounds\":[{\"protocol\":\"vless\",\"settings\":{}}]})\");"
            model_lines[295] = "    model.updateModel(DockerContainer::Xray, withNative(baseConfig(\"xhttp\", \"reality\", \"\"), broken));"
            model_lines[296] = "    model.setFingerprint(\"firefox\");"
            model_lines[297] = ""
            model_lines[298] = "    QVERIFY2(!model.getProtocolConfig().hasClientConfig(),"
            model_lines[299] = "             \"a native config that cannot be rebuilt must be dropped so the server issues a fresh one\");"
            model_lines[306] = "    QVERIFY(!model.hasUnsavedChanges());"
            model_lines[307] = ""
            model_lines[308] = "    const QString original = model.fingerprint();"
            model_lines[309] = "    model.setFingerprint(\"firefox\");"
            model_lines[310] = "    QVERIFY(model.hasUnsavedChanges());"
            model_lines[311] = "    model.setFingerprint(original);"
            model_lines[312] = "    QVERIFY(!model.hasUnsavedChanges());"
            model_cpp.write_text("\n".join(model_lines) + "\n")

            matrix_cpp = tests_dir / "testXrayGeneratorMatrix.cpp"
            matrix_lines = [f"// line {i}" for i in range(1, 200)]
            matrix_lines[184] = "                                         field == \"udp443\" ? \"xtls-rprx-vision\" : \"\");"
            matrix_lines[185] = "    XrayServerConfig after = before;"
            matrix_lines[186] = "    if (field == \"fingerprint\")"
            matrix_lines[187] = "        after.fingerprint = QStringLiteral(\"firefox\");"
            matrix_lines[188] = "    else if (field == \"uplinkMethod\")"
            matrix_lines[189] = "        after.xhttp.uplinkMethod = QStringLiteral(\"PATCH\");"
            matrix_lines[190] = "    else if (field == \"uplinkChunkSize\")"
            matrix_cpp.write_text("\n".join(matrix_lines) + "\n")

            uo.validate_debian_patches(upstream, ROOT)

            matrix_cpp.write_text("// mismatched content\n")
            with self.assertRaises(RuntimeError):
                uo.validate_debian_patches(upstream, ROOT)

    def test_write_client_config_handles_comments_and_permissions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.env"
            lines = ["# generated comment"]
            for name in uo.CLIENT_CONFIG_VARIABLES:
                val = "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----" if name.endswith("PUBLIC_KEY") else f"https://{name.lower()}.example/"
                lines.append(f"export {name}={val!r}")
            src.write_text("\n".join(lines) + "\n")

            pkg = root / "debian"
            pkg.mkdir()
            with patch.dict(os.environ, {"CLIENT_CONFIG_FILE": str(src)}, clear=False):
                uo.write_client_config(pkg)

            out = pkg / "client-config.env"
            self.assertEqual(out.stat().st_mode & 0o777, 0o600)
            self.assertIn("\\n", out.read_text())

    def test_parse_build_depends_parses_real_control(self):
        deps = uo.parse_build_depends(ROOT / "debian/control")
        self.assertIn("debhelper-compat (= 13)", deps)
        self.assertIn("golang-go", deps)

    def test_obs_controller_checks_dirty_and_revision_match(self):
        dirty_xml = (
            '<resultlist state="1">'
            '<result repository="xUbuntu_26.04" arch="x86_64" dirty="true">'
            '<status package="amneziavpn-secure" code="succeeded"/>'
            "</result></resultlist>"
        )
        clean_xml = (
            '<resultlist state="1">'
            '<result repository="xUbuntu_26.04" arch="x86_64">'
            '<status package="amneziavpn-secure" code="succeeded"/>'
            "</result></resultlist>"
        )
        other_arch_failed_xml = (
            '<resultlist state="1">'
            '<result repository="xUbuntu_26.04" arch="aarch64">'
            '<status package="amneziavpn-secure" code="failed"/>'
            "</result>"
            '<result repository="xUbuntu_26.04" arch="x86_64">'
            '<status package="amneziavpn-secure" code="succeeded"/>'
            "</result></resultlist>"
        )

        with patch.object(oc, "api", return_value=dirty_xml):
            self.assertFalse(oc.build_succeeded())

        def fake_api_mismatch(path):
            if "_result" in path:
                return clean_xml
            if "_buildinfo" in path:
                return "<buildinfo><srcmd5>old-rev</srcmd5></buildinfo>"
            if "expand=1" in path:
                return '<directory srcmd5="new-rev"/>'
            raise AssertionError(path)

        with patch.object(oc, "api", side_effect=fake_api_mismatch):
            self.assertFalse(oc.build_succeeded())

        def fake_api_match(path):
            if "_result" in path:
                return clean_xml
            if "_buildinfo" in path:
                return "<buildinfo><srcmd5>cur-rev</srcmd5></buildinfo>"
            if "expand=1" in path:
                return '<directory srcmd5="cur-rev"/>'
            raise AssertionError(path)

        with patch.object(oc, "api", side_effect=fake_api_match):
            self.assertTrue(oc.build_succeeded())

        with TemporaryDirectory() as tmp, patch.object(oc, "STATE", Path(tmp)):
            state = Path(tmp)
            (state / "candidate.json").write_text('{"srcmd5": "cur-rev", "prepared_at": 1}')

            def fake_wait_api(path):
                if "_result" in path:
                    return other_arch_failed_xml
                if "_buildinfo" in path:
                    return "<buildinfo><srcmd5>cur-rev</srcmd5></buildinfo>"
                if "expand=1" in path:
                    return '<directory srcmd5="cur-rev"/>'
                raise AssertionError(path)

            with (
                patch.object(oc, "api", side_effect=fake_wait_api),
                patch.object(oc, "reconcile") as mock_reconcile,
            ):
                oc.wait_for_builds()
                mock_reconcile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
