"""Setup flag admission and exact existing-runtime call; WSL/builds are mocked."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'tools/scenario_cli.ps1'

class CatalogSetup(unittest.TestCase):
    def powershell(self,script):
        encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
        return subprocess.run([shutil.which('powershell.exe'),' -NoProfile'.strip(),'-NonInteractive','-EncodedCommand',encoded],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)

    def test_rejected_flag_never_reaches_setup_or_other_actions(self):
        for args in (['check','-BuildCatalogSourceExporter'],['setup','-BuildCatalogSourceExporter','-BuildExporter'],['setup','-BuildCatalogSourceExporter','-BuildPortableSourceExporter']):
            call=subprocess.run([shutil.which('powershell.exe'),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SCRIPT),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
            self.assertNotEqual(call.returncode,0)
            self.assertIn(b'BuildCatalogSourceExporter requires setup',call.stderr)

    def test_build_calls_only_additive_target_through_locked_existing_runtime(self):
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        script="""
        $taskErrors=$null
        $taskAst=[System.Management.Automation.Language.Parser]::ParseFile(SCRIPT,[ref]$null,[ref]$taskErrors)
        if($taskErrors.Count){throw 'Invalid setup syntax'}
        $taskFunction=$taskAst.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Build-CatalogSourceExporter'},$true)
        if(!$taskFunction){throw 'Missing explicit build function'}
        Invoke-Expression $taskFunction.Extent.Text
        function Check-Upstream { [pscustomobject]@{ok=$true} }
        function wsl.exe { $script:catalogTaskArguments=@($args);$global:LASTEXITCODE=0 }
        $root=ROOT
        Build-CatalogSourceExporter
        $script:catalogTaskArguments | ConvertTo-Json -Compress
        """.replace('SCRIPT',quote(SCRIPT)).replace('ROOT',quote(ROOT))
        call=self.powershell(script)
        self.assertEqual(call.returncode,0,call.stderr.decode(errors='replace'))
        args=json.loads(call.stdout.decode().strip().splitlines()[-1])
        self.assertEqual(args,['--distribution','Ubuntu-24.04','--cd',str(ROOT/'transport'),'--exec','bash','./workflow.sh','python','-B','./catalog_exporter_setup.py','build','--windows-root',str(ROOT)])
        source=SCRIPT.read_text(encoding='utf-8')
        self.assertIn("'setup'{if($BuildCatalogSourceExporter){Build-CatalogSourceExporter;exit 0};if($BuildPortableSourceExporter){Build-PortableSourceExporter;exit 0}",source)
        self.assertIn('--locked --no-install', (ROOT/'transport/workflow.sh').read_text())

if __name__=='__main__':unittest.main()
