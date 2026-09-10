"""Windows rooted handles for the bounded artifact collector.

This is intentionally not a general filesystem abstraction.  It supports the
single, controlled directory shape used by evidence collection and refuses to
follow reparse points while resolving each component relative to an already
opened directory handle.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_LIST_DIRECTORY = 0x0001
_FILE_SHARE_READ = 0x0001
_FILE_SHARE_WRITE = 0x0002
_FILE_SHARE_DELETE = 0x0004
_FILE_OPEN = 0x00000001
_FILE_CREATE = 0x00000002
_FILE_OPEN_IF = 0x00000003
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_OBJ_CASE_INSENSITIVE = 0x00000040
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035
_STATUS_DELETE_PENDING = 0xC0000056
_COMPONENT_RE = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.ULONG),
        ("root_directory", wintypes.HANDLE),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", wintypes.LPVOID),
        ("security_quality_of_service", wintypes.LPVOID),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("status", ctypes.c_long), ("information", ctypes.c_size_t)]


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("creation", wintypes.FILETIME),
        ("access", wintypes.FILETIME),
        ("write", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("delete_file", wintypes.BOOL)]


def available() -> bool:
    return os.name == "nt"


def _handle_value(handle):
    return getattr(handle, "value", handle)


def _api():
    if not available():
        raise OSError("Windows rooted artifact collection is unavailable")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FileInfo),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes), ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID, wintypes.ULONG, wintypes.DWORD, wintypes.ULONG,
        wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG,
    ]
    ntdll.NtCreateFile.restype = ctypes.c_long
    return kernel32, ntdll


def _close(kernel32, handle) -> None:
    if handle is not None and _handle_value(handle) not in (None, 0, _INVALID_HANDLE_VALUE):
        kernel32.CloseHandle(handle)


def _mark_delete(kernel32, handle) -> None:
    """Mark an opened file object for deletion without reopening by path."""
    info = _FileDispositionInfo(True)
    if not kernel32.SetFileInformationByHandle(
            handle, 4, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())


def _try_mark_delete(kernel32, handle) -> None:
    """Best-effort cleanup that never replaces the original wrapping error."""
    if handle is None:
        return
    try:
        _mark_delete(kernel32, handle)
    except BaseException:
        pass


def _check_component(name: str) -> None:
    if not isinstance(name, str) or not _COMPONENT_RE.fullmatch(name):
        raise ValueError("ARTIFACT_COLLECTION_COMPONENT_INVALID")


def _open_relative(kernel32, ntdll, parent, name: str, *, directory: bool, exclusive: bool):
    _check_component(name)
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = _UnicodeString(
        len(name) * 2, (len(name) + 1) * 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(unicode_name),
        _OBJ_CASE_INSENSITIVE, None, None,
    )
    status_block = _IoStatusBlock()
    handle = wintypes.HANDLE()
    desired = (_GENERIC_READ if directory else (_GENERIC_READ | _GENERIC_WRITE | _DELETE)) | _SYNCHRONIZE
    disposition = _FILE_CREATE if exclusive else _FILE_OPEN_IF
    options = (_FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE) | _FILE_SYNCHRONOUS_IO_NONALERT
    if directory:
        options |= _FILE_OPEN_REPARSE_POINT
    status = ntdll.NtCreateFile(
        ctypes.byref(handle), desired, ctypes.byref(attributes),
        ctypes.byref(status_block), None, 0,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        disposition, options, None, 0,
    )
    if status < 0:
        unsigned_status = status & 0xffffffff
        if unsigned_status == _STATUS_DELETE_PENDING:
            raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE")
        if unsigned_status == _STATUS_OBJECT_NAME_COLLISION and exclusive:
            raise ValueError("ARTIFACT_COLLECTION_ATTEMPT_CONFLICT" if directory
                             else "ARTIFACT_DESTINATION_CONFLICT")
        raise OSError(f"NtCreateFile failed: 0x{status & 0xffffffff:08x}")
    if directory:
        info = _FileInfo()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            _close(kernel32, handle)
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            _close(kernel32, handle)
            raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE")
    return handle


def _open_base(kernel32, base: Path):
    handle = kernel32.CreateFileW(
        str(base), _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None, _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_OPEN_REPARSE_POINT,
        None,
    )
    if _handle_value(handle) in (None, 0, _INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error())
    info = _FileInfo()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _close(kernel32, handle)
        raise ctypes.WinError(ctypes.get_last_error())
    if info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        _close(kernel32, handle)
        raise ValueError("ARTIFACT_COLLECTION_PATH_ESCAPE")
    return handle


@contextmanager
def attempt(base: Path, request_key: str, attempt_name: str):
    """Yield an exclusive attempt path and a handle rooted in the task dir."""
    _check_component("evidence")
    _check_component("collected")
    _check_component(request_key)
    _check_component(attempt_name)
    kernel32, ntdll = _api()
    handles = []
    try:
        parent = _open_base(kernel32, base)
        handles.append(parent)
        for component in ("evidence", "collected", request_key):
            child = _open_relative(kernel32, ntdll, parent, component, directory=True, exclusive=False)
            handles.append(child)
            parent = child
        created = _open_relative(kernel32, ntdll, parent, attempt_name, directory=True, exclusive=True)
        handles.append(created)
        yield base / "evidence" / "collected" / request_key / attempt_name, created
    finally:
        for handle in reversed(handles):
            _close(kernel32, handle)


@contextmanager
def output(attempt_handle, name: str):
    """Create one final output exclusively under the already-open attempt."""
    import msvcrt

    kernel32, ntdll = _api()
    handle = _open_relative(kernel32, ntdll, attempt_handle, name, directory=False, exclusive=True)
    fd = None
    stream = None
    try:
        try:
            fd = msvcrt.open_osfhandle(_handle_value(handle), os.O_BINARY | os.O_RDWR)
        except BaseException:
            # The native file already exists, but ownership has not crossed
            # into a Python fd.  Keep the same native handle for cleanup.
            _try_mark_delete(kernel32, handle)
            raise
        handle = None
        try:
            stream = os.fdopen(fd, "w+b", buffering=0)
        except BaseException:
            # fdopen failed after ownership crossed to the fd.  Resolve the
            # native handle from that fd and mark that same object deleted
            # before the fd is closed in finally.
            try:
                native_handle = msvcrt.get_osfhandle(fd)
            except BaseException:
                native_handle = None
            _try_mark_delete(kernel32, native_handle)
            raise
        fd = None
        yield stream
    finally:
        if stream is not None:
            stream.close()
        if fd is not None:
            os.close(fd)
        _close(kernel32, handle)


def verify(stream, expected_sha256: str, expected_size: int) -> None:
    """Verify bytes and size through the same open output object."""
    stream.flush()
    os.fsync(stream.fileno())
    stat_result = os.fstat(stream.fileno())
    if stat_result.st_size != expected_size:
        raise ValueError("ARTIFACT_COPY_INVALID")
    stream.seek(0)
    digest = __import__("hashlib").sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    if digest.hexdigest() != expected_sha256:
        raise ValueError("ARTIFACT_COPY_INVALID")


def discard(stream) -> None:
    """Delete a known-uncommitted output through its current open handle."""
    import msvcrt

    kernel32, _ = _api()
    handle = msvcrt.get_osfhandle(stream.fileno())
    _mark_delete(kernel32, handle)
