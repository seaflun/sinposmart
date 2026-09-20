# -*- coding: utf-8 -*-
import os
import sys


if {
    "--read-only-login-acceptance",
    "--startup-smoke-test",
    "--audit-fixture-acceptance",
} & set(sys.argv[1:]):
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    os.environ.pop("QML_FORCE_DISK_CACHE", None)


from qt_app.main import main


if __name__ == "__main__":
    raise SystemExit(main())
