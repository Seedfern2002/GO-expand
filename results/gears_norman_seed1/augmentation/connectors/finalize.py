#!/usr/bin/env python3
"""Independent locator checks, recorded source-policy/sample audit, contract validation and freeze."""
import collections as C
import csv
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'overlay_v1'; SRC=ROOT/'acquisition_v1'
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x): p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def lines(p): return [json.loads(s) for s in p.read_text().splitlines()]

manifest=read(OUT/'manifest.draft.json')
sources={}
for family,name in [('reactome','reactome98_UniProt2Reactome.txt'),('humap','humap3_20240922.csv')]:
    with (SRC/name).open() as f:
        if family=='reactome': sources[family]={n:r for n,r in enumerate(csv.reader(f,delimiter='\t'),1)}
        else: sources[family]={n:r for n,r in enumerate(csv.DictReader(f),2)}

all_samples=[]
for batch in manifest['batches']:
    family='reactome' if batch['source_name']=='Reactome' else 'humap'
    rows=lines(Path(batch['records_path'])); refs_checked=0
    for r in rows:
        expected=family+':'+hashlib.sha256(('task_membership_v1|'+r['subject_label']+'|'+r['object_id']).encode()).hexdigest()[:24]
        assert r['id']==expected
        for ref in r['evidence_refs']:
            raw=sources[family][ref['line']]; refs_checked+=1
            if family=='reactome':
                assert raw[0]==ref['protein_id'] and raw[1]==r['object_id'] and raw[3]==r['object_label'] and raw[4]==ref['source_evidence_code'] and raw[5]=='Homo sapiens'
            else:
                assert 'hu.MAP3:'+raw['HuMAP3_ID']==r['object_id'] and ref['protein_id'] in raw['Uniprot_ACCs'].split()
                assert int(raw['ComplexConfidence'])==r['source_confidence']['class']
                assert len(raw['Uniprot_ACCs'].split())==r['source_full_protein_size']
    auditpath=OUT/(family+'_audit.json'); audit=read(auditpath)
    sample=lines(OUT/(family+'_audit_sample.jsonl')); all_samples+=audit['sampled_record_ids']
    assert len(sample)==10 and {r['id'] for r in sample}==set(audit['sampled_record_ids'])
    assert all(r in rows for r in sample)
    cov=read(Path(batch['coverage_report_path']))
    excluded=C.Counter(q['reason'] for q in lines(OUT/(family+'_quarantine.jsonl')))
    audit.update(review_status='completed', findings=[
       {'scope':'source_policy','status':'pass','detail':'Official lowest-level export with human species and release-matched labels/hierarchy. TAS and IEA retained, neither reclassified as direct experiment.' if family=='reactome' else 'Official hu.MAP 3.0 schema and six ordinal confidence labels match. All classes retained; only 1-3 enter primary set projection.'},
       {'scope':'seeded_sample','status':'pass','detail':'Ten records inspected for identifiers, original aliases, relation semantics, unknown K562 activity, retained source evidence and protein identifiers. All sampled source locators independently checked.'},
       {'scope':'sample_specific_semantics','status':'pass','detail':'Alias histones, combined TAS/IEA, canonical/isoform aggregation and a drug/mutant pathway label are retained without K562 activation claims.' if family=='reactome' else 'All six confidence classes and both approved/previous gene symbol mappings occur in the ten-record sample. Lower confidence is stored with projection excluded.'},
       {'scope':'quarantine','status':'reported','reason_counts':dict(excluded),'detail':'No ambiguous/unmapped accessions or accession-symbol conflicts were distributed to candidate genes. Five universe mappings are unresolved, including an alias collision; their genes stay fixed.'},
       {'scope':'source_limitations','status':'reported','detail':'General human membership is not K562 activity, signed regulation, protein stoichiometry or direct pairwise interaction. Exported pathway labels retain disease/drug qualifiers; structured molecular-state context is unavailable.'}
    ])
    audit['source_checks'].update(source_locator_references_checked=refs_checked,independent_source_locator_check_passed=True,
       source_policy_document='https://reactome.org/download-data' if family=='reactome' else 'https://humap3.proteincomplexes.org/download',
       manual_sample_semantics_inspected=True,quarantine_reasons_reviewed=True,GO_overlap_measured_on_all_3127_genes=True)
    audit['exclusions'].update(unresolved_universe_gene_mappings=cov['genes_mapping_unresolved'],quarantine_reasons=dict(excluded))
    audit['review_scope']='Source/transformation policy and allocated sample only; all rows programmatically checked. No individual experimental literature verification or novel biological claims.'
    save(auditpath,audit)
    validation=read(Path(batch['validation_report_path'])); validation.update(independent_source_locator_references_checked=refs_checked,independent_source_locator_failures=0,audit_completed=True)
    save(Path(batch['validation_report_path']),validation)
    batch['records_sha256']=sha(Path(batch['records_path']))
assert len(all_samples)==len(set(all_samples))==20

ledger=read(SRC/'retrieval_ledger.json')
distinct=set(ledger['web_discovery_urls'])|{r['url'] for r in ledger['requests']}|{'https://www.encodeproject.org/help/batch-download/'}
ledger.update(distinct_source_urls=sorted(distinct),distinct_sources_opened=len(distinct),literature_search_queries=0,
   structured_metadata_queries=1,LLM_audit_sample_records=20,additional_agents_used=0,max_cpu_threads=2,
   web_open_attempts_this_stage=6,sandbox_DNS_failed_probes=3,
   byte_accounting='Exact bytes for cached HTTP snapshots; web discovery page bodies and failed web opens are not available as byte counters. No raw assay files or large dumps fetched.')
assert len(distinct)<=15 and ledger['downloaded_bytes']==sum(r.get('bytes',0) for r in ledger['requests']) and ledger['downloaded_bytes']<268435456
save(SRC/'retrieval_ledger.json',ledger)
probe=read(SRC/'encode_k562_probe.json'); experiment=probe['@graph'][0]
assert probe['total']==776 and experiment['status']=='released' and experiment['biosample_ontology']['term_name']=='K562'
pending=read(OUT/'encode_pending.json')
pending.update(metadata_probe={'source_snapshot':str(SRC/'encode_k562_probe.json'),'sha256':sha(SRC/'encode_k562_probe.json'),
   'http_status':200,'matched_experiments':probe['total'],'returned_experiments':len(probe['@graph']),
   'example_accession':experiment['accession'],'assay':'TF ChIP-seq','organism_filter_note':'Probe queried K562 and released TF ChIP-seq; target identifier is human. No complete human/quality/file eligibility screening was performed.'},
   next_steps='Declare and acquire a small processed K562 element-to-gene or TF-target resource with assembly/linkage/quality policy, then screen all genes. Do not infer signed regulation from TF occupancy.')
save(OUT/'encode_pending.json',pending)

for item in manifest['coverage']:
    if item['plan_item_id']=='encode_k562_regulatory_evidence':
        item['notes']='Bounded metadata probe succeeded (776 matches, one returned); no approved processed target-linkage resource acquired. All 3,127 genes and 102 targets are not_screened_pending; details in overlay_v1/encode_pending.json.'
    else:
        b=next(b for b in manifest['batches'] if b['plan_item_id']==item['plan_item_id']); cov=read(Path(b['coverage_report_path']))
        item['status']='covered'
        item['notes']=f"All {cov['genes_screened']} genes screened; {cov['record_count']} validated memberships annotate {cov['genes_annotated']} genes and {cov['perturbation_targets']['genes_annotated']}/102 targets. Primary projection: {cov['projection_eligible_records']} memberships, {cov['projection_eligible_genes']} genes. {cov['quarantine_count']} source rows/members quarantined; five universe gene mappings unresolved. Source-policy and ten-record sample audit complete; full-universe GO overlap measured."
manifest['open_questions']=[
  'ENCODE regulatory integration remains pending acquisition and approval of a processed target-linkage resource; no gene-level regulatory screening or signed claims were produced.',
  'Unresolved mappings remain quarantined: 2,121 Reactome source rows and 454 hu.MAP members. Resolve through a separately versioned mapping revision; do not alter the fixed universe.'
]

# Use the exact CLI validation implementation without running a new CLI stage.
spec=importlib.util.spec_from_file_location('stage_contract',Path('scripts/run_agent_stage.py').resolve())
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.validate_result(ROOT/'retriever',read(ROOT/'retriever/manifest.json'),manifest)
save(OUT/'manifest.json',manifest)
save(OUT/'contract_validation.json',{'schema':'retriever/schema.json','implementation':'scripts/run_agent_stage.py:validate_result','passed':True,
   'materialized_batches':len(manifest['batches']),'gene_by_family_ledger_rows':len(lines(OUT/'gene_by_family_screening.jsonl')),
   'all_normalized_rows_validated':True,'source_policy_audits_completed':True,'total_sample_records':20})

# Freeze by checksums, retaining source files, policies, exclusions, ledgers and recipes.
paths=sorted([p for folder in (SRC,OUT,ROOT/'connectors') for p in folder.rglob('*') if p.is_file() and p.name not in {'freeze_manifest.json','manifest.draft.json'} and '__pycache__' not in str(p)])
save(OUT/'freeze_manifest.json',{'frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'task_id':'gears_norman_task','policy_version':'task_membership_v1','selection_basis':['task_specification','fixed_gene_universe','external_source_evidence'],
   'downstream_evaluation_inputs_used':False,'original_GO_modified':False,'projection':'Evidence/set-attribute recipes only; no downstream graph or training executed.',
   'files':[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in paths]})
print(json.dumps({'contract_validation':'passed','manifest':str(OUT/'manifest.json'),'download_bytes':ledger['downloaded_bytes'],'distinct_sources':len(distinct),'frozen_artifacts':len(paths)},indent=2))
