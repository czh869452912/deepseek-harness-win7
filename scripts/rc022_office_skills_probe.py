"""Pinned Office skill resources, environment sections and discovery failures."""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.cordis import Context
from dsh.skill.registry import SkillRegistry
from dsh.skill.office_current import CurrentOfficeSkills,ASSETS

WORKSPACE=None


def cases():
    rows=[dict(environment=value) for value in ['workspace-dependencies','user']]
    for raw in ['# No frontmatter','---\n\n---\nBody','---\nnull\n---\nBody','---\nscalar\n---\nBody',
                '---\nname: office-docx\n---\nBody','---\ndescription: 3\n---\nBody','---\ndescription: ""\n---\nBody',
                '---\ndescription: [unclosed\n---\nBody','---\ndescription: first\ndescription: second\n---\nBody',
                '---\ndescription: yes\n---\n\ufeff Body \u00a0','---\ndescription: 2026-11-17\n---\nBody',
                '---\na: &a {description: merged}\n<<: *a\n---\nBody','---\ndescription: "正文"\n---\n\t Body \ufeff',
                '---\r\ndescription: line\r\n---\r\nBody\r\n']:
        rows.append(dict(raw=raw))
    rows.append(dict(missing=True))
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=Path(tempfile.mkdtemp(prefix='g-')).resolve()
    (output/'pytest-workspace-mapping.json').write_text(json.dumps(dict(format='dsh-release-workspace@2',temporary_parent=str(WORKSPACE.parent),execution_path=str(WORKSPACE),retained_path=str(output/'files'),scope='Owned paired Office skills workspace')),encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(directory=str(WORKSPACE/'source'),cases=cases())),encoding='utf-8');return [path]


async def observe(directory=None):
    directory=Path(directory or WORKSPACE/'native');rows=[]
    for index,entry in enumerate(cases()):
        root=directory/str(index);shutil.copytree(str(ASSETS),str(root));docx=root/'office-docx'/'SKILL.md'
        original=docx.read_bytes()
        if 'raw' in entry:docx.write_bytes(entry['raw'].encode('utf-8'))
        if entry.get('missing'):docx.unlink()
        ctx=Context();warnings=[];ctx.logger.warn=lambda message,*args:warnings.append(str(message))
        try:
            await ctx.plugin(SkillRegistry)
            fiber=await ctx.plugin(CurrentOfficeSkills,dict(assetRoot=str(root),pythonEnvironment=entry.get('environment','workspace-dependencies')))
            catalog=await ctx.skills.snapshot();loaded=[await ctx.skills.get(name) for name in ['office','office-docx','office-pptx','office-xlsx']]
            await ctx.skills.get('office-docx');after=await ctx.skills.snapshot();before=len(warnings)
            await fiber.dispose();docx.write_bytes(original)
            fiber=await ctx.plugin(CurrentOfficeSkills,dict(assetRoot=str(root),pythonEnvironment=entry.get('environment','workspace-dependencies')))
            recovered=await ctx.skills.get('office-docx')
            await fiber.dispose();removed=await ctx.skills.list()
            row=dict(catalog=catalog,loaded=loaded,after=after,warnings=before,recovered=recovered,removed=removed)
        finally:await ctx.fiber.dispose()
        def normalize(value):
            if isinstance(value,str):return value.replace(str(root),'<assets>').replace(str(root).replace('\\','/'),'<assets>')
            if isinstance(value,list):return [normalize(item) for item in value]
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            return value
        rows.append(normalize(row))
    return rows


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_office_skills.mts',scope='Actual mounted Office skill provider/registry, pinned body resources, Python environment text, missing/invalid metadata, warning deduplication, recovery and disposal.',prepare=prepare,
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/skill/office_current.py',ROOT/'packages/skill/skill-office/package.json',*sorted(ASSETS.rglob('SKILL.md'))])
    finally:
        if WORKSPACE is not None:
            from scripts.verify_release import retain_regression_workspace
            retain_regression_workspace(WORKSPACE,Path(sys.argv[sys.argv.index('--output')+1]).resolve()/'files')
