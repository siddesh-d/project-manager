import os
import shutil


def create_file(target_path, content):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target_path, flags, 0o666)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as handle:
            handle.write(str(content))
    except Exception:
        try:
            os.unlink(target_path)
        except OSError:
            pass
        raise


def create_folder(target_path):
    os.mkdir(target_path)


def delete_file(target_path):
    os.unlink(target_path)


def delete_folder(target_path):
    shutil.rmtree(target_path)
