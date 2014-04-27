def pytest_ignore_collect(path, config):
    basename = path.basename

    if "setup.py" in basename or "configure.py" in basename or 'pytest' in basename:
        return True
