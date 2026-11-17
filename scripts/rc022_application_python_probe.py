"""Official candidate composition with the explicit Win7 Python PTC overlay."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_application_probe as application

if __name__=='__main__':
    application.PLATFORM_PATCHES=[str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.EXECUTE_PTC=True
    raise SystemExit(application.main())
