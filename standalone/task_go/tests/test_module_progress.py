"""Check recovery boundaries and bounded retries for complete module runs."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.knowledge import sha256
from engine.module_progress import archive_attempt, load_progress
from place_module_recipes import worker
from place_modules import write
import test_module_graph as fixtures


class ModuleProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.fixture=fixtures.ModuleGraphTests();self.fixture.setUp()
        f=self.fixture
        data={"baseline_graph.json":f.graph,"modules.json":f.catalog,"placement_evidence.json":f.facts,
              "module_batches.json":[{"id":"b1","modules":["EXT:P","EXT:C"]}]}
        write(self.root/"task.json",{"task_id":"source_task"})
        for name,value in data.items():write(self.root/"inputs"/name,value)
        write(self.root/"inputs/manifest.json",{"task_sha256":sha256(self.root/"task.json"),"files":[
            {"path":"inputs/"+name,"sha256":sha256(self.root/"inputs"/name)} for name in data]})
        write(self.root/"runtime.json",{"batch_attempts":2})

    def test_failed_attempts_are_archived_without_changing_committed_graph(self):
        graph,_=load_progress(self.root,self.fixture.graph,self.fixture.catalog,self.fixture.facts,[])
        directory=self.root/"batches/b1/editor_1";directory.mkdir(parents=True)
        (directory/"events.jsonl").write_text('saved failed invocation\n')
        self.assertEqual(archive_attempt(self.root,"b1"),1)
        self.assertEqual((self.root/"failed_batches/b1_attempt_001/editor_1/events.jsonl").read_text(),'saved failed invocation\n')
        self.assertEqual(json.loads((self.root/"graph/current.json").read_text()),graph)

    def test_batch_retries_stop_at_the_budget_and_keep_partial_progress(self):
        previous=Path.cwd()
        try:
            with patch("place_module_recipes.run_batch",side_effect=ValueError("Invalid source-bound proposal")) as call, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code=worker(self.root)
        finally:os.chdir(previous)
        self.assertEqual(code,1)
        self.assertEqual(call.call_count,2)
        self.assertEqual(len(list((self.root/"failed_batches").iterdir())),2)
        self.assertEqual(json.loads((self.root/"graph/current.json").read_text())["revision"],0)
        self.assertFalse((self.root/"knowledge_graph/freeze_manifest.json").exists())


if __name__=="__main__":unittest.main()
