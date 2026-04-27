import hashlib
import os
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, ClassVar, Union


class EntryType(Enum):
    file: bytes = b"file"
    directory: bytes = b"directory"
    symlink: bytes = b"symlink"


@dataclass
class Record:
    digest: bytes
    name: str

    digest_size: ClassVar[int] = 32
    max_name_length: ClassVar[int] = 0xFFFF
    header_format: ClassVar[str] = ">32sH"  # sha256 digest(32 bytes) + name_len(u16)
    header_size: ClassVar[int] = struct.calcsize(header_format)

    def pack(self) -> bytearray:
        encoded_name = self.name.encode("utf-8")
        encoded_size = len(encoded_name)

        if encoded_size > self.max_name_length:
            raise ValueError(f"the file name is too long: {self.name}")

        if len(self.digest) != self.digest_size:
            raise ValueError(f"digest must be {self.digest_size} bytes")

        buf = bytearray(self.header_size + encoded_size)
        struct.pack_into(self.header_format, buf, 0, self.digest, encoded_size)
        buf[self.header_size:] = encoded_name
        return buf


class HashTree:
    def __init__(
        self,
        hasher: Callable = hashlib.sha256,
        chunk_size: int = 1024 * 1024,
    ):
        self.hasher = hasher
        self.chunk_size = chunk_size

    def hash(self, obj: Union[bytes, bytearray, Path]) -> bytes:
        h = self.hasher()
        if isinstance(obj, bytes) or isinstance(obj, bytearray):
            h.update(obj)
        elif isinstance(obj, Path):
            with open(obj, "rb") as f:
                for chunk in iter(lambda: f.read(self.chunk_size), b""):
                    h.update(chunk)
        else:
            raise ValueError(f"object must be bytes or Path, got {type(obj)}")

        return h.digest()

    def __pack_record(self, child_hash: bytes, name: str) -> bytearray:
        return Record(child_hash, name).pack()

    def get_hex_digest(self, path: Path, *, full_hash: bool = True) -> str:
        return self.get_digest(path, full_hash=full_hash).hex()

    def __symlink_handler(self, path: Path):
        # HASH(b"symlink" || symlink.target)
        target = os.readlink(path)
        obj = EntryType.symlink.value + target.encode("utf-8")
        return self.hash(obj)

    def __file_handler(self, path: Path, *, full_hash: bool = True):
        # HASH(b"file" || file.content)
        obj = path
        if not full_hash:
            obj = path.name.encode("utf-8")

        content_hash = self.hash(obj)
        obj = EntryType.file.value + content_hash
        return self.hash(obj)

    def get_digest(self, path: Path, *, full_hash: bool = True) -> bytes:
        # check if the symlink itself was changed
        if path.is_symlink():
            return self.__symlink_handler(path)

        if not path.exists():
            raise FileNotFoundError(f"path {path} does not exist")

        # check if the file was changed
        if path.is_file():
            return self.__file_handler(path, full_hash=full_hash)

        if not path.is_dir():
            raise NotImplementedError(f"Unsupported file type: {path}")

        # check if the directory was changed.
        children = []
        for entry in os.scandir(path):
            name = entry.name
            encoded_name = name.encode("utf-8")

            entry_path = Path(entry.path)

            if entry.is_symlink():
                child_hash = self.__symlink_handler(entry_path)
            elif entry.is_file(follow_symlinks=False):
                child_hash = self.__file_handler(entry_path, full_hash=full_hash)
            elif entry.is_dir(follow_symlinks=False):
                child_hash = self.get_digest(entry_path, full_hash=full_hash)
            else:
                raise NotImplementedError(f"Unsupported file type: {entry.path}")

            children.append((encoded_name, name, child_hash))

        # sort entry items according to its utf-8 byte order
        children.sort(key=lambda x: x[0])

        # HASH(b"directory" || serialized children records)
        buf = bytearray()
        buf.extend(EntryType.directory.value)
        for _, name, child_hash in children:
            buf.extend(self.__pack_record(child_hash, name))

        return self.hash(buf)
