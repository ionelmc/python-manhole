def pytest_ignore_collect(path, config):
    basename = path.basename

    for name in (
        "setup.py",
        "configure.py",
        "README.rst",
        "pytest",
    ):
        if name in basename:
            return True
