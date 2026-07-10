#!/usr/bin/env python3
"""Generate package/THIRD-PARTY-NOTICES.txt from a built app's lib/ directory.

The R2 access layer (bin/r2client.py) is pure standard library and has no
third-party runtime dependencies. The three direct requirements pinned in
package/lib/requirements.txt (splunktaucclib, splunk-sdk, solnlib - plus
urllib3, pinned directly for the Splunk 9.4 OpenSSL floor) pull in transitive
dependencies when `ucc-gen build` resolves them, so lib/ ends up with more
packages than requirements.txt lists directly.

This script reads the actual, currently-resolved set of packages from a
built app's lib/*.dist-info/METADATA files (installed-metadata is the only
place license identifiers and license files are self-consistent for the
exact versions actually shipped) and writes a THIRD-PARTY-NOTICES.txt that
reproduces each package's own bundled license text verbatim.

Usage:
    ucc-gen build --source package --ta-version <version>
    python3 tools/generate_third_party_notices.py \
        --lib output/TA_cloudflare_r2/lib \
        --out package/THIRD-PARTY-NOTICES.txt

Re-run this after any dependency bump (in package/lib/requirements.txt) so
the notices file reflects what's actually resolved and shipped, not a
hand-maintained guess.
"""

import argparse
import glob
import os
import re
import sys


# Normalizes the raw, inconsistently-formatted License / License-Expression
# metadata values PyPI packages actually ship (e.g. "Apache 2.0", "Apache 2",
# a bare license-text URL) to a single SPDX-style identifier per license, so
# packages that are the same license display and cross-reference-match
# consistently regardless of how each project happened to format its field.
_LICENSE_NORMALIZE = {
    "apache 2.0": "Apache-2.0",
    "apache2.0": "Apache-2.0",
    "apache 2": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "http://www.apache.org/licenses/license-2.0": "Apache-2.0",
    "https://www.apache.org/licenses/license-2.0": "Apache-2.0",
    "bsd": "BSD",
    "mit": "MIT",
    "mit license": "MIT",
    "psfl": "PSF-2.0",
    "psf": "PSF-2.0",
}


def normalize_license(raw):
    if not raw:
        return raw
    return _LICENSE_NORMALIZE.get(raw.strip().lower(), raw.strip())


LICENSE_FILE_CANDIDATES = (
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "licenses/LICENSE",
    "licenses/LICENSE.txt",
    "licenses/LICENSE.md",
)


def parse_metadata(meta_path):
    """Parse a wheel METADATA/PKG-INFO file into a dict of top-level fields."""
    data = {}
    license_files = []
    with open(meta_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            # METADATA body starts after the first blank line; header fields
            # are one-per-line with "Key: value" and never start with
            # whitespace, so this is enough to stop at the body.
            if line.strip() == "":
                break
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "License-File":
                license_files.append(v)
            elif k in ("Name", "Version", "License", "License-Expression", "Home-page"):
                data.setdefault(k, v)
    data["License-Files"] = license_files
    return data


def find_license_files(dist_info_dir, declared_license_files):
    """Return license file paths (relative to dist_info_dir) that actually exist.

    Prefers the License-File fields declared in METADATA (PEP 639); falls
    back to conventional filenames, then to any file whose name looks like
    a license/copying/notice file.
    """
    found = []
    for name in declared_license_files:
        for candidate in (name, os.path.join("licenses", name)):
            if os.path.exists(os.path.join(dist_info_dir, candidate)):
                found.append(candidate)
                break
    if found:
        return found

    for candidate in LICENSE_FILE_CANDIDATES:
        if os.path.exists(os.path.join(dist_info_dir, candidate)):
            return [candidate]

    # Last resort: anything license-ish directly under dist-info or its
    # licenses/ subdir (skip generated code like packaging's licenses/*.py).
    for sub in ("", "licenses"):
        d = os.path.join(dist_info_dir, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if re.search(r"licen[cs]e|copying|notice", name, re.I) and not name.endswith(".py"):
                found.append(os.path.join(sub, name) if sub else name)
    return found


def collect_packages(lib_dir):
    packages = []
    for dist_info in sorted(glob.glob(os.path.join(lib_dir, "*.dist-info"))):
        meta_path = os.path.join(dist_info, "METADATA")
        if not os.path.exists(meta_path):
            meta_path = os.path.join(dist_info, "PKG-INFO")
        if not os.path.exists(meta_path):
            continue
        meta = parse_metadata(meta_path)
        name = meta.get("Name", os.path.basename(dist_info))
        version = meta.get("Version", "")
        license_id = normalize_license(meta.get("License-Expression") or meta.get("License")) or "UNKNOWN"
        homepage = meta.get("Home-page")
        licfiles = find_license_files(dist_info, meta.get("License-Files", []))
        packages.append(
            {
                "dist_info": os.path.basename(dist_info),
                "name": name,
                "version": version,
                "license": license_id,
                "homepage": homepage,
                "licfiles": licfiles,
            }
        )
    return packages


def render(packages):
    lines = []
    lines.append("THIRD-PARTY NOTICES")
    lines.append("====================")
    lines.append("")
    lines.append("This add-on (Cloudflare R2 Log Ingestion, TA_cloudflare_r2) is licensed under")
    lines.append("the Apache License, Version 2.0 - see LICENSE.txt.")
    lines.append("")
    lines.append("The R2 access layer this add-on adds (bin/r2client.py, bin/cloudflare_r2_helper.py,")
    lines.append("bin/test_sigv4.py) is original code using the Python standard library only; it")
    lines.append("has no third-party runtime dependencies.")
    lines.append("")
    lines.append("The packages listed below are bundled in lib/ because they are required by the")
    lines.append("Splunk-supplied UCC toolchain (splunktaucclib, the modular input SDK, and their")
    lines.append("own transitive dependencies) - this add-on's code does not import most of them")
    lines.append("directly. They are reproduced here, with their license text, in accordance with")
    lines.append("the terms of those licenses. Each package's original license file is also")
    lines.append("preserved unmodified under lib/<package>-<version>.dist-info/ in this package.")
    lines.append("")
    lines.append("Summary")
    lines.append("-------")
    lines.append("")
    namew = max(len(p["name"]) for p in packages)
    verw = max(len(p["version"]) for p in packages)
    licw = max(len(p["license"]) for p in packages)
    header = f"{'Package'.ljust(namew)}  {'Version'.ljust(verw)}  {'License'.ljust(licw)}"
    lines.append(header)
    lines.append("-" * len(header))
    for p in packages:
        lines.append(f"{p['name'].ljust(namew)}  {p['version'].ljust(verw)}  {p['license'].ljust(licw)}")
    lines.append("")
    lines.append("=" * 78)
    lines.append("")

    for p in packages:
        title = f"{p['name']} {p['version']} ({p['license']})"
        lines.append(title)
        lines.append("-" * len(title))
        if p["homepage"]:
            lines.append(f"Homepage: {p['homepage']}")
        lines.append("")
        if p["licfiles"]:
            for i, licfile in enumerate(p["licfiles"]):
                if i > 0:
                    lines.append("")
                    lines.append(f"--- alternative license option ({os.path.basename(licfile)}) ---")
                    lines.append("")
                path = os.path.join(p["_lib_dir"], p["dist_info"], licfile)
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines.append(f.read().rstrip("\n"))
        elif p.get("_see_also"):
            lines.append(f"[No license file bundled in {p['dist_info']}.]")
            lines.append(
                f"This package declares the same '{p['license']}' license identifier as "
                f"{p['_see_also']} in this file; see that entry for the full license text."
            )
        else:
            lines.append(
                f"[No license file found in {p['dist_info']}; license per package metadata: "
                f"{p['license']}. Verify this package's license manually before publishing.]"
            )
        lines.append("")
        lines.append("=" * 78)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lib", required=True, help="Path to a built app's lib/ directory")
    ap.add_argument("--out", required=True, help="Output path for THIRD-PARTY-NOTICES.txt")
    args = ap.parse_args()

    if not os.path.isdir(args.lib):
        sys.exit(f"error: {args.lib} is not a directory - build the app first (ucc-gen build)")

    packages = collect_packages(args.lib)
    if not packages:
        sys.exit(f"error: no *.dist-info/METADATA files found under {args.lib}")

    for p in packages:
        p["_lib_dir"] = args.lib

    # For any package with no bundled license file, see if another package
    # in this same build declares the *identical* license identifier and
    # does have a bundled file - if so, cross-reference it by name instead
    # of guessing at license text. Otherwise, flag for manual review.
    by_license = {}
    for p in packages:
        if p["licfiles"]:
            by_license.setdefault(p["license"], p)
    for p in packages:
        if p["licfiles"]:
            continue
        match = by_license.get(p["license"])
        if match:
            p["_see_also"] = f"{match['name']} {match['version']}"
        else:
            print(
                f"warning: no license file found for {p['name']} {p['version']} "
                f"({p['dist_info']}), and no other package in this build shares its "
                f"'{p['license']}' license identifier to cross-reference - review manually",
                file=sys.stderr,
            )

    text = render(packages)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {args.out} ({len(text)} bytes, {len(packages)} packages)")


if __name__ == "__main__":
    main()
