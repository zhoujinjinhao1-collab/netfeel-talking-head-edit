"""Download the optional, checksum-pinned Source Han font pair to a project."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

FILES = {
    "SourceHanSerifSC-Heavy.otf": (
        "https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/OTF/SimplifiedChinese/SourceHanSerifSC-Heavy.otf",
        "d033af54f96530476faed924ab5d5e9e6ef0833495670fd57bab9a7758398048",
    ),
    "SourceHanSansSC-Medium.otf": (
        "https://raw.githubusercontent.com/adobe-fonts/source-han-sans/release/OTF/SimplifiedChinese/SourceHanSansSC-Medium.otf",
        "1df61d31687d04fd2f928a3bb6ca6cd61f0e988cc267cf317f32406edbb49f70",
    ),
}
LICENSES = {
    "OFL-SourceHanSerif.txt": "https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/LICENSE.txt",
    "OFL-SourceHanSans.txt": "https://raw.githubusercontent.com/adobe-fonts/source-han-sans/release/LICENSE.txt",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in FILES.items():
        path = args.dest / name
        data = path.read_bytes() if path.exists() else urllib.request.urlopen(url, timeout=90).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Font checksum mismatch: {name}; use a verified local font instead.")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
        print(f"Verified {name}", flush=True)
    for name, url in LICENSES.items():
        path = args.dest / name
        if not path.exists():
            data = urllib.request.urlopen(url, timeout=45).read()
            with path.open("xb") as stream:
                stream.write(data)
    print("Downloaded fonts keep their SIL Open Font License; see the OFL files.")


if __name__ == "__main__":
    main()
