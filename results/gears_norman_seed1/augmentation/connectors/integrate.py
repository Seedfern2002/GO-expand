#!/usr/bin/env python3
"""Task-wide direct membership overlay, policy v1. No downstream data inputs."""
import collections as C
import csv
import hashlib
import json
import pickle
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'acquisition_v1'
OUT = ROOT / 'overlay_v1'
OUT.mkdir(exist_ok=True)
POLICY = 'task_membership_v1'

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''): h.update(b)
    return h.hexdigest()

def save(name, obj):
    path = OUT / name
    path.write_text(json.dumps(obj, indent=2, sort_keys=True)+'\n')
    return str(path)

def jsonl(name, rows):
    path = OUT / name
    with path.open('w') as f:
        for row in rows: f.write(json.dumps(row, sort_keys=True)+'\n')
    return str(path)

u = json.loads((ROOT/'inputs/gene_universe.json').read_text())
genes, targets = u['graph_genes'], u['perturbation_targets']
assert len(genes)==len(set(genes))==3127 and len(targets)==len(set(targets))==102 and set(targets)<=set(genes)
universe = set(genes)
ledger = json.loads((SRC/'retrieval_ledger.json').read_text())
sources = {r['name']:r for r in ledger['requests'] if r['outcome']=='acquired'}
for name, meta in sources.items(): assert digest(SRC/name)==meta['sha256']
hgnc, symbols, aliases, proteins = {}, C.defaultdict(set), C.defaultdict(set), C.defaultdict(set)
with (SRC/'hgnc_complete_set.txt').open() as f:
    for row in csv.DictReader(f, delimiter='\t'):
        if row['status']!='Approved': continue
        hid=row['hgnc_id']; hgnc[hid]=row; symbols[row['symbol']].add(hid)
        for key in ('alias_symbol','prev_symbol'):
            for s in row[key].split('|'):
                if s: aliases[s].add(hid)
        for p in row['uniprot_ids'].split('|'):
            if p: proteins[p].add(hid)

def resolve_symbol(s):
    candidates=symbols.get(s,set()) or aliases.get(s,set())
    return (next(iter(candidates)) if len(candidates)==1 else None), ('approved_symbol' if symbols.get(s) else 'alias_or_previous_symbol') if len(candidates)==1 else ('ambiguous' if candidates else 'unmapped')

mapping={}; reverse=C.defaultdict(list)
for g in genes:
    hid,status=resolve_symbol(g)
    mapping[g]={'gene':g,'hgnc_id':hid,'status':status,'approved_symbol':hgnc[hid]['symbol'] if hid else None}
    if hid: reverse[hid].append(g)
for hid, gs in reverse.items():
    if len(gs)>1:
        for g in gs: mapping[g]['status']='ambiguous_universe_collision'; mapping[g]['hgnc_id']=None
hid_to_gene={m['hgnc_id']:g for g,m in mapping.items() if m['hgnc_id']}
jsonl('gene_mapping.jsonl',[mapping[g] for g in sorted(genes)])

def protein_map(p):
    # Isoform suffix is retained; canonical accession lookup is an explicit aggregation.
    base=p.split('-')[0]; ids=proteins.get(base,set())
    return (next(iter(ids)) if len(ids)==1 else None), ('unambiguous_accession' if len(ids)==1 else 'ambiguous_accession' if ids else 'unmapped_accession')

labels={}; human=set()
with (SRC/'reactome98_pathways.txt').open() as f:
    for n,row in enumerate(csv.reader(f,delimiter='\t'),1):
        assert len(row)==3
        pid,label,species=row; labels[pid]=label
        if species=='Homo sapiens': assert pid.startswith('R-HSA-'); human.add(pid)
hierarchy=[]
with (SRC/'reactome98_hierarchy.txt').open() as f:
    for n,row in enumerate(csv.reader(f,delimiter='\t'),1):
        assert len(row)==2 and all(x in labels for x in row)
        if row[0] in human or row[1] in human:
            assert all(x in human for x in row)
            hierarchy.append({'parent':row[0],'child':row[1],'source_line':n})
jsonl('reactome_hierarchy.jsonl',hierarchy)

context={'taxon_id':'NCBITaxon:9606','source_scope':'general_human','cell_type':'K562','cell_activity':'unknown','treatment':'unknown','molecular_state':'not_provided_by_export','cofactors':'not_provided_by_export'}
groups={'reactome':{},'humap':{}}
quarantine={'reactome':[],'humap':[]}
source_stats={'reactome':C.Counter(),'humap':C.Counter()}
complexes=[]

def add(family,g,obj,label,protein,line,code,confidence=None,extra=None):
    key=(g,obj)
    if key not in groups[family]:
        rid=family+':'+hashlib.sha256((POLICY+'|'+g+'|'+obj).encode()).hexdigest()[:24]
        groups[family][key]={'id':rid,'subject_id':mapping[g]['hgnc_id'],'subject_label':g,
          'subject_approved_symbol':mapping[g]['approved_symbol'],'object_id':obj,'object_label':label,
          'relation':'member_of_pathway' if family=='reactome' else 'predicted_member_of_complex',
          'polarity':'not_applicable','context':dict(context),'evidence_class':'database_derived',
          'source_evidence_semantics':'curated_or_inferred_pathway_export' if family=='reactome' else 'integrated_predicted_complex',
          'source_confidence':confidence,'projection_eligible':family=='reactome' or confidence['class']<=3,
          'mapping_status':mapping[g]['status'],'source_proteins':[], 'evidence_refs':[],
          'transformation_version':POLICY,'membership_scope':'direct_exported_lowest_level' if family=='reactome' else 'source_defined_complex'}
        if extra: groups[family][key].update(extra)
    row=groups[family][key]
    if protein not in row['source_proteins']: row['source_proteins'].append(protein)
    row['evidence_refs'].append({'snapshot':'reactome98_UniProt2Reactome.txt' if family=='reactome' else 'humap3_20240922.csv','line':line,'source_evidence_code':code,'protein_id':protein})

with (SRC/'reactome98_UniProt2Reactome.txt').open() as f:
    for n,row in enumerate(csv.reader(f,delimiter='\t'),1):
        s=source_stats['reactome']; s['imported_rows']+=1
        if len(row)!=6: quarantine['reactome'].append({'line':n,'reason':'invalid_columns'}); s['quarantined_rows']+=1; continue
        p,pid,url,label,code,species=row
        if species!='Homo sapiens': s['excluded_nonhuman_rows']+=1; continue
        s['human_rows']+=1
        hid,status=protein_map(p)
        reason=None
        if pid not in human or labels.get(pid)!=label or code not in {'TAS','IEA'} or not url.endswith(pid): reason='invalid_pathway_label_species_evidence_or_uri'
        elif hid is None: reason=status
        if reason:
            quarantine['reactome'].append({'line':n,'protein_id':p,'pathway_id':pid,'reason':reason}); s['quarantined_rows']+=1; continue
        g=hid_to_gene.get(hid)
        if not g: s['excluded_outside_universe_rows']+=1; continue
        add('reactome',g,pid,label,p,n,code); s['accepted_source_rows']+=1; s['evidence_'+code]+=1

confidence_labels={1:'Extremely High',2:'Very High',3:'High',4:'Moderate High',5:'Medium High',6:'Medium'}
seen=set()
with (SRC/'humap3_20240922.csv').open() as f:
    reader=csv.DictReader(f)
    assert reader.fieldnames==['HuMAP3_ID','ComplexConfidence','Uniprot_ACCs','genenames']
    for n,row in enumerate(reader,2):
        s=source_stats['humap']; s['imported_complex_rows']+=1
        cid=row['HuMAP3_ID']; conf=int(row['ComplexConfidence']); assert conf in confidence_labels and re.fullmatch(r'huMAP3_\d+\.\d+',cid) and cid not in seen
        seen.add(cid); accs=row['Uniprot_ACCs'].split(); names=row['genenames'].split()
        assert accs and len(accs)==len(set(accs))
        resolved=[]
        for p in accs:
            s['imported_member_rows']+=1
            hid,status=protein_map(p); reason=None
            if hid is None: reason=status
            elif not any(resolve_symbol(sym)[0]==hid for sym in names): reason='accession_symbol_conflict'
            if reason:
                quarantine['humap'].append({'line':n,'complex_id':cid,'protein_id':p,'reason':reason,'source_symbols':names}); s['quarantined_member_rows']+=1; continue
            g=hid_to_gene.get(hid)
            if not g: s['excluded_outside_universe_member_rows']+=1; continue
            resolved.append((g,p)); s['accepted_source_member_rows']+=1
        size=len({g for g,p in resolved})
        complexes.append({'complex_id':'hu.MAP3:'+cid,'source_line':n,'source_full_protein_size':len(accs),'source_symbols':names,'source_proteins':accs,'in_universe_gene_size':size,'confidence_class':conf,'projection_eligible':conf<=3,'shared_membership_connectivity':size>=2})
        for g,p in resolved:
            add('humap',g,'hu.MAP3:'+cid,cid,p,n,'source_integrated_prediction',{'class':conf,'label':confidence_labels[conf],'scale':'ordinal_not_probability'},
                {'source_full_protein_size':len(accs),'in_universe_gene_size':size,'shared_membership_connectivity':size>=2})
jsonl('humap_complexes.jsonl',complexes)

# Immutable GO input is only used to measure overlap after source selection.
go_path=Path('data/raw/gears/gene2go_all.pkl').resolve()
go_sha=digest(go_path)
with go_path.open('rb') as f: go_raw=pickle.load(f)
go={g:set(go_raw.get(g,[])) for g in genes}
go_inv=C.defaultdict(set)
for g,terms in go.items():
    for term in terms: go_inv[term].add(g)

def overlap(rows):
    ext=C.defaultdict(set); inv=C.defaultdict(set)
    for r in rows:
        if r['projection_eligible']: ext[r['subject_label']].add(r['object_id']); inv[r['object_id']].add(r['subject_label'])
    counts=C.Counter()
    for g in genes:
        neighbors=set().union(*(inv[x] for x in ext[g])) if ext[g] else set()
        neighbors.discard(g)
        for h in neighbors:
            if h<=g: continue
            counts['external_comembership_pairs']+=1
            common=go[g]&go[h]
            if common: counts['also_share_any_GO_term']+=1
            else: counts['no_shared_GO_term']+=1
            union=go[g]|go[h]
            if union and len(common)/len(union)>0.1: counts['also_pass_baseline_GO_Jaccard_0.1']+=1
    return dict(counts, genes_with_GO=sum(bool(go[g]) for g in genes), universe_size=len(genes),
        original_GO_path=str(go_path), original_GO_sha256=go_sha,
        metric='Unordered distinct gene pairs sharing a primary external attribute; GO Jaccard threshold before top-k pruning. No graph construction or downstream scores.',
        literal_GO_namespace_overlap=0)

batches=[]; screening=[]
for family,planid,version,source_file,source_name in [
 ('reactome','reactome_human_pathway_membership','98','reactome98_UniProt2Reactome.txt','Reactome'),
 ('humap','humap3_human_complex_membership','3.0 / file 20240922','humap3_20240922.csv','hu.MAP')]:
    rows=sorted(groups[family].values(),key=lambda x:x['id'])
    for row in rows: row['source_proteins'].sort(); row['source_version']=version
    recpath=jsonl(family+'_records.jsonl',rows)
    jsonl(family+'_quarantine.jsonl',quarantine[family])
    # Complete, independent checks on every emitted record and source locator.
    failures=[]; ids=set(); keys=set()
    for r in rows:
        errors=[]; g=r['subject_label']; key=(r['subject_id'],r['object_id'],r['relation'])
        if r['id'] in ids or key in keys: errors.append('duplicate')
        ids.add(r['id']); keys.add(key)
        if g not in universe or not r['subject_id'] or r['subject_id']!=mapping[g]['hgnc_id']: errors.append('subject_mapping')
        if r['polarity']!='not_applicable' or r['context']['cell_activity']!='unknown' or r['context']['taxon_id']!='NCBITaxon:9606': errors.append('semantics')
        if not r['object_label'] or not r['evidence_refs'] or not r['source_proteins']: errors.append('required_fields')
        if any(e['line']<1 or e['snapshot']!=source_file or e['protein_id'] not in r['source_proteins'] for e in r['evidence_refs']): errors.append('source_locator')
        if family=='reactome' and (r['object_id'] not in human or any(e['source_evidence_code'] not in {'TAS','IEA'} for e in r['evidence_refs'])): errors.append('reactome_policy')
        if family=='humap' and (r['source_confidence']['class'] not in confidence_labels or r['projection_eligible']!=(r['source_confidence']['class']<=3) or not 1<=r['in_universe_gene_size']<=r['source_full_protein_size']): errors.append('humap_policy')
        if errors: failures.append({'id':r['id'],'errors':errors})
    assert not failures
    accepted={r['subject_label'] for r in rows}; eligible={r['subject_label'] for r in rows if r['projection_eligible']}
    counts=C.Counter(r['subject_label'] for r in rows); pc=C.Counter(r['subject_label'] for r in rows if r['projection_eligible'])
    flagged_genes=set()
    for q in quarantine[family]:
        syms=q.get('source_symbols',[])
        for sym in syms:
            hid,_=resolve_symbol(sym)
            if hid in hid_to_gene: flagged_genes.add(hid_to_gene[hid])
    for g in sorted(genes):
        status='annotated' if g in accepted else 'mapping_ambiguous_or_unmapped' if not mapping[g]['hgnc_id'] else 'no_mapped_evidence'
        screening.append({'plan_item_id':planid,'gene':g,'is_perturbation_target':g in targets,'status':status,'record_count':counts[g],'projection_eligible_record_count':pc[g], 'in_complex_with_quarantined_member':g in flagged_genes,'mapping_status':mapping[g]['status']})
    coverage={'universe_size':len(genes),'genes_screened':len(genes),'genes_annotated':len(accepted),'record_count':len(rows),
       'projection_eligible_genes':len(eligible),'projection_eligible_records':sum(r['projection_eligible'] for r in rows),
       'projection_excluded_records':sum(not r['projection_eligible'] for r in rows),'genes_without_accepted_evidence':len(universe-accepted),
       'genes_mapping_unresolved':sum(not m['hgnc_id'] for m in mapping.values()),'genes_in_complexes_with_quarantined_members':len(flagged_genes),
       'perturbation_targets':{'universe_size':len(targets),'genes_screened':len(targets),'genes_annotated':len(set(targets)&accepted),'projection_eligible_genes':len(set(targets)&eligible),'genes_without_accepted_evidence':len(set(targets)-accepted)},
       'source_row_reconciliation':dict(source_stats[family]),'quarantine_count':len(quarantine[family]),
       'unresolved_policy':'All unresolved source records quarantined. No mapped evidence is not a claim of biological absence.',
       'singleton_in_universe_records':sum(r.get('in_universe_gene_size')==1 for r in rows),
       'GO_overlap_report':str(OUT/(family+'_go_overlap.json'))}
    s=source_stats[family]
    if family=='reactome': assert s['imported_rows']==s['excluded_nonhuman_rows']+s['quarantined_rows']+s['excluded_outside_universe_rows']+s['accepted_source_rows']
    else: assert s['imported_member_rows']==s['quarantined_member_rows']+s['excluded_outside_universe_member_rows']+s['accepted_source_member_rows']
    covpath=save(family+'_coverage.json',coverage)
    save(family+'_go_overlap.json',overlap(rows))
    # Allocate ten samples per family; stratification plus seeded random fill.
    rng=random.Random(17); strata=C.defaultdict(list)
    for r in rows: strata[(r['mapping_status'],str(r['source_confidence']['class']) if family=='humap' else ','.join(sorted({e['source_evidence_code'] for e in r['evidence_refs']})))].append(r)
    samples=[]
    for key in sorted(strata):
        if len(samples)<10: samples.append(rng.choice(strata[key]))
    remaining=[r for r in rows if r not in samples]; samples+=rng.sample(remaining,min(10-len(samples),len(remaining)))
    jsonl(family+'_audit_sample.jsonl',samples)
    auditpath=save(family+'_audit.json',{'review_method':'source_policy_and_seeded_stratified_sample_audit','sampling_seed':17,
      'sampled_record_ids':[r['id'] for r in samples],'findings':[], 'review_status':'awaiting_sample_inspection',
      'exclusions':{'source_records_quarantined':len(quarantine[family]),'projection_excluded':coverage['projection_excluded_records']},
      'source_checks':{'snapshot_checksum_verified':True,'every_normalized_row_validated':True,'source_row_reconciliation_passed':True,'individual_literature_verification':False},
      'sample_artifact':str(OUT/(family+'_audit_sample.jsonl'))})
    valpath=save(family+'_validation.json',{'validated_rows':len(rows),'failed_rows':len(failures),'failures':failures,
       'checks':['schema_required_fields','stable_ids','unique_membership_keys','human_species','subject_mapping','source_locator','evidence_codes_or_confidence','polarity','context','cardinalities','source_reconciliation'],
       'audit_report_path':auditpath,'source_rows_checked':dict(source_stats[family])})
    srcnames=['hgnc_complete_set.txt',source_file]+(['reactome98_pathways.txt','reactome98_hierarchy.txt','reactome_version.txt','reactome_license.html'] if family=='reactome' else [])
    provpath=save(family+'_provenance.json',{'source_name':source_name,'source_version':version,'snapshots':{n:sources[n] for n in srcnames},
       'transformation_version':POLICY,'program_path':str(Path(__file__).resolve()),'program_sha256':digest(Path(__file__)),
       'mapping_policy':'HGNC approved symbols precede unambiguous previous/alias symbols; UniProt accessions primary, isoform suffix retained with explicit canonical accession gene aggregation; ambiguous accessions and symbol conflicts quarantined.',
       'hgnc_snapshot_version':sources['hgnc_complete_set.txt']['headers'].get('Last-Modified'),'gene_mapping_path':str(OUT/'gene_mapping.jsonl'),
       'source_evidence_notes':'TAS and IEA retained as exported; membership export omits molecular-state and disease conditions, which remain unknown.' if family=='reactome' else 'Integrated predicted complexes; source complex size and all proteins preserved, confidence ordinal not probability; source names used as consistency set, never positional mapping.',
       'license':{'uri':'https://reactome.org/license','statement':'Data and derived data files: CC0; separate illustrations license does not apply to membership tables','snapshot':'reactome_license.html'} if family=='reactome' else {'uri':'https://humap3.proteincomplexes.org/download','statement':'CC0 per official download documentation'},
       'hierarchy_path':str(OUT/'reactome_hierarchy.jsonl') if family=='reactome' else None,
       'projection_recipe':{'version':POLICY,'relation':'direct_membership_only','ancestor_expansion':False,'confidence_classes':[1,2,3] if family=='humap' else None,'physical_clique':False,'original_GO_modified':False},
       'audit_report_path':auditpath,'quarantine_path':str(OUT/(family+'_quarantine.jsonl'))})
    batches.append({'id':family+'_membership_v1','plan_item_id':planid,'source_name':source_name,'source_version':version,'source_uri':sources[source_file]['url'],
       'records_path':recpath,'records_sha256':digest(Path(recpath)),'provenance_path':provpath,'validation_report_path':valpath,'coverage_report_path':covpath})

for g in sorted(genes): screening.append({'plan_item_id':'encode_k562_regulatory_evidence','gene':g,'is_perturbation_target':g in targets,'status':'not_screened_pending'})
jsonl('gene_by_family_screening.jsonl',screening)
save('encode_pending.json',{'status':'pending','universe_size':len(genes),'genes_screened':0,'genes_not_screened_pending':len(genes),'perturbation_targets_pending':len(targets),'reason':'Bounded metadata probe only; no approved processed target linkage resource acquired. Binding metadata does not establish signed regulation.'})
assert digest(go_path)==go_sha
save('manifest.draft.json',{'schema_version':'2.0','task_id':'gears_norman_task','batches':batches,'coverage':[
  {'plan_item_id':b['plan_item_id'],'status':'partial','notes':'Bulk full-universe screening completed; awaiting final source-policy/sample review.'} for b in batches]+[
  {'plan_item_id':'encode_k562_regulatory_evidence','status':'pending','notes':'All 3127 genes and 102 targets not_screened_pending; bounded metadata probe recorded, no approved target linkage resource.'}],
 'open_questions':[]})
print(json.dumps({'batches':[{ 'family':b['source_name'], **json.loads(Path(b['coverage_report_path']).read_text())} for b in batches], 'shared_mapping_statuses':dict(C.Counter(m['status'] for m in mapping.values())),'audit_records_total':20},indent=2))
