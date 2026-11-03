# -*- coding: utf-8 -*-
import glob
import py_compile
import sys

for f in glob.glob(r"D:\ConsPlus\server\*.py"):
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        print("COMPILE_FAIL", f, e)
        sys.exit(1)
print("COMPILE_OK")

sys.path.insert(0, r"D:\ConsPlus")
import server.app as a  # noqa: E402
print("IMPORT_OK port=", a.config.PORT, "host=", a.config.HOST)
print("ROUTES=", sorted({r.rule for r in a.app.url_map.iter_rules()}))
