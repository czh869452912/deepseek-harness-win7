"""Private native package-command adapter used by the current management seam."""
import json
import os
from pathlib import Path
import sys

# Executed by absolute filename from a profile, including embedded Python.
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from dsh.boot.plugin_registry_policy import UNSPECIFIED
from dsh.boot.python_package_query import (PackageQueryError,npm_configuration,
    configured_registry,query_metadata)


def package_command(env=None):
    options=dict(command=str(Path(sys.executable).resolve()),args=[str(Path(__file__).resolve())])
    if env is not None:options['env']=dict(env)
    return options


def _view(argv,directory):
    if len(argv)<2:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','view requires a package spec')
    spec=argv[1];fields=[];registry=None
    for argument in argv[2:]:
        if argument.startswith('--registry='):registry=argument[len('--registry='):]
        elif argument in ('--json','--config.fetch-retries=0'):continue
        elif argument.startswith('-'):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','unsupported metadata option')
        else:fields.append(argument)
    if not fields:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','metadata fields are required')
    return query_metadata(directory,spec,fields,registry)


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    try:
        if argv==['config','get','registry']:
            print(configured_registry(npm_configuration(os.getcwd())));return 0
        if argv and argv[0]=='view':
            value=_view(argv,os.getcwd())
            if value is not UNSPECIFIED:print(json.dumps(value,ensure_ascii=False,separators=(',',':')))
            return 0
        raise PackageQueryError('ERR_DSH_PYTHON_PACKAGE_OPERATION_UNAVAILABLE','native package mutation is not available in this query adapter')
    except PackageQueryError as error:
        print(json.dumps(dict(error=dict(code=error.code,message=error.message)),ensure_ascii=False))
        print(str(error),file=sys.stderr);return 1
    except Exception as error:
        # Never print an exception body containing configured URLs or secrets.
        code='ERR_DSH_PACKAGE_QUERY';message='native package query failed: '+type(error).__name__
        print(json.dumps(dict(error=dict(code=code,message=message))))
        print(code+' '+message,file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
