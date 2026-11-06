#!/usr/bin/env python3
"""Bounded, serial source acquisition; immutable successful snapshots and request ledger."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'acquisition_v1'
ROOT.mkdir(exist_ok=True)
LIMIT = 268435456

def fetch(name, url):
    ledger = ROOT / 'retrieval_ledger.json'
    state = json.loads(ledger.read_text()) if ledger.exists() else {
        'budget_bytes': LIMIT, 'downloaded_bytes': 0, 'search_queries': 0,
        'planning_open_attempts': 3, 'max_source_open_budget': 15,
        'web_discovery_urls': [
            'https://reactome.org/download-data',
            'https://humap3.proteincomplexes.org/download',
            'https://reactome.org/ContentService/data/database/version',
            'https://download.reactome.org/current/',
            'https://download.reactome.org/version/UniProt2Reactome.txt',
            'https://humap3.proteincomplexes.org/static/downloads/humap3/hu.MAP3.0_complexes_wConfidenceScores_total15326_wGenenames_20240922.csv'],
        'requests': [], 'max_concurrent_requests_used': 1,
        'discovery_note': 'Planning used three opens, zero searches. Web could read official download pages; binary/CSV links were not ingested through web. Sandbox DNS failed on three serial probes; no snapshot bytes returned.'}
    target = ROOT / name
    if target.exists():
        print(json.dumps({'cached': name, 'bytes': target.stat().st_size})); return
    entry = {'url': url, 'name': name, 'retrieved_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    distinct = set(state['web_discovery_urls']) | {r['url'] for r in state['requests']} | {
        'https://www.encodeproject.org/help/batch-download/', url}
    if len(distinct) > 15:
        raise RuntimeError('Distinct-source open budget would be exceeded')
    tmp = target.with_suffix(target.suffix + '.part')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GO-overlay-source-acquisition/1.0'})
        with urllib.request.urlopen(req, timeout=45) as response, tmp.open('wb') as out:
            entry.update(resolved_url=response.url, status=response.status, headers=dict(response.headers))
            while True:
                chunk = response.read(min(1048576, LIMIT-state['downloaded_bytes']+1))
                if not chunk: break
                state['downloaded_bytes'] += len(chunk)
                if state['downloaded_bytes'] > LIMIT: raise RuntimeError('Download budget exhausted')
                out.write(chunk)
        tmp.rename(target)
        entry.update(bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest(), outcome='acquired')
    except Exception as exc:
        entry.update(outcome='unavailable', error=repr(exc))
        if tmp.exists(): tmp.unlink()
    state['requests'].append(entry)
    state['distinct_source_urls'] = sorted(distinct)
    state['distinct_sources_opened'] = len(distinct)
    ledger.write_text(json.dumps(state, indent=2)+'\n')
    print(json.dumps(entry))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('name'); parser.add_argument('url')
    args = parser.parse_args(); fetch(args.name,args.url)
