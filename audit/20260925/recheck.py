"""Read-only audit of current application and research artifacts; outputs beside this file."""
from pathlib import Path
import sys, json, sqlite3, hashlib, re
import pandas as pd

OUT = Path(__file__).resolve().parent
APP = OUT.parents[1]
ROOT = APP.parent
RESEARCH = ROOT / '技术链' / '出海预测'
RUN = RESEARCH / 'outputs/01_demand_construction/02_full_text_label_run'
sys.path.insert(0, str(APP))
from server import logic, sc, graph
from server.geo import geo_extract

def ro(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, check_same_thread=False)
con = ro(APP / 'kb/kb-2023.sqlite')
sccon = ro(APP / 'kb/kb-sc-2023.sqlite')
logic._conn = lambda: con
sc._conn = lambda: sccon

def records(df):
    return json.loads(df.to_json(orient='records', force_ascii=False))
def save_csv(df, name):
    df.to_csv(OUT / name, index=False, encoding='utf-8-sig')
def metrics(y, p):
    y, p = y.astype(bool), p.astype(bool)
    tp, fp, fn, tn = [int(s.sum()) for s in [y&p, ~y&p, y&~p, ~y&~p]]
    n=tp+fp+fn+tn
    acc=(tp+tn)/n
    pe=((tp+fp)*(tp+fn)+(tn+fn)*(tn+fp))/n**2
    return dict(n=n,tp=tp,fp=fp,fn=fn,tn=tn,accuracy=acc,precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                kappa=(acc-pe)/(1-pe) if pe<1 else None)

result={}
result['tables']={}
for tag,db in [('main',con),('supply',sccon)]:
    result['tables'][tag]={t:db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                           for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
result['meta']=logic.meta()
chunks=pd.read_sql('SELECT * FROM chunks',con)
claims=logic._claims(); panel=logic._panel(); ag=logic.agg()
result['base']={'firms':int(chunks.scode.nunique()),'chunk_firmyears':len(chunks[['scode','year']].drop_duplicates()),
 'years':[int(chunks.year.min()),int(chunks.year.max())], 'claims_labels':claims.program_label.value_counts().to_dict(),
 'chunk_labels':chunks.program_label.value_counts(dropna=False).to_dict(),
 'chunk_duplicate_ids':int(chunks.chunk_id.duplicated().sum()),
 'claim_duplicate_ids':int(claims[['chunk_id','claim_number']].duplicated().sum()),
 'panel_duplicate_keys':int(panel[['scode','year']].duplicated().sum()),
 'panel_demand':panel.overseas_demand.value_counts(dropna=False).astype(int).to_dict(),
 'panel_columns':list(panel.columns),'industry_tags_counts':{k:len(v) for k,v in logic.industry_tags().items()}}
source=pd.read_csv(RUN/'classified_all.csv',dtype={'scode':str},low_memory=False)
source['scode']=source.scode.str.zfill(6)
result['source_summary']=json.loads((RUN/'summary.json').read_text(encoding='utf-8'))
result['source_summary'].pop('keyword_dictionary',None)
result['chunk_industry']=chunks['industry'].value_counts().to_dict() if 'industry' in chunks else 'column absent'

# Window reconciliation: replicate the historical missing-as-zero rule vs explicit observed zero.
dem=panel[panel.overseas_demand.eq(1)].copy()
old=dem[dem.overseas_sub_count.fillna(0).eq(0)&dem.overseas_rev_share.fillna(0).le(0)].copy()
strict=dem[dem.overseas_sub_count.eq(0)&dem.overseas_rev_share.eq(0)].copy()
diff=old.merge(strict[['scode','year']],on=['scode','year'],how='left',indicator=True)
diff=diff[diff['_merge'].eq('left_only')].drop(columns='_merge')
diff['missing_sub']=diff.overseas_sub_count.isna();diff['missing_revenue']=diff.overseas_rev_share.isna()
save_csv(diff,'window_109_minus_88.csv')
result['windows']={'demand_panel':len(dem),'old_fill_zero':len(old),'observed_both_zero':len(strict),
 'old_firms':int(old.scode.nunique()),'strict_firms':int(strict.scode.nunique()),
 'difference':len(diff),'missing_patterns':records(diff.groupby(['missing_sub','missing_revenue']).size().reset_index(name='n')),
 'current_window_distribution':ag.window_type.value_counts(dropna=False).to_dict(),
 'difference_current_types':records(diff[['scode','year']].merge(ag[['scode','year','window_type']],how='left',on=['scode','year']).groupby('window_type',dropna=False).size().reset_index(name='n')),
 'demand_missing_either_layout':int(dem[['overseas_sub_count','overseas_rev_share']].isna().any(axis=1).sum())}
unknown=ag[ag.overseas_demand.isna()].copy()
save_csv(unknown[['scode','year','window_type','n_deploy','n_intent']],'unknown_label_cases.csv')
result['unknown_label_cases']=records(unknown[['scode','year','window_type','n_deploy','n_intent']])
result['windows']['first_years_per_firm_distribution']=ag[ag.window_type.eq('first')].groupby('scode').size().value_counts().to_dict()
result['unknown_label_cases_source']=records(panel[panel.overseas_demand.isna()][['scode','year','demand_label_complete']])

# Human-label reconciliation. Keep both possible label definitions rather than silently relabel.
human_path=RESEARCH/'archives/pre_current_demand_mainline_20260901/outputs/02_model_training/intent_annotation_478/annotation_template.csv'
h=pd.read_csv(human_path,dtype={'scode':str},low_memory=False)
m=h.merge(source[['chunk_id','program_demand','label_complete','text','text_raw','text_clean']],on='chunk_id',how='left',validate='one_to_one',suffixes=('_human','_current'),indicator=True)
normalize=lambda x:re.sub(r'\s+','',str(x))
m['text_matches_current']=m.apply(lambda r:any(normalize(r['text_human'])==normalize(r[c]) for c in ['text_current','text_raw','text_clean']),axis=1)
m['human_strict']=m.stage2_label.eq('future_overseas_intent')
m['human_broad']=m.stage2_label.isin(['future_overseas_intent','latent_overseas_demand_signal'])
m['machine_demand']=m.program_demand.eq(1)
save_csv(m[['annotation_id','chunk_id','observation_id','scode','year','source_type','stage2_label','program_demand','label_complete','text_matches_current','human_strict','human_broad','machine_demand']],'human_validation_recomputed.csv')
result['human']={'n':len(m),'unique_chunks':int(m.chunk_id.nunique()),'unique_firmyears':len(m[['scode','year']].drop_duplicates()),
 'unique_firms':int(m.scode.nunique()),'join':m['_merge'].value_counts().to_dict(),
 'text_match_count':int(m.text_matches_current.sum()),'label_complete':m.label_complete.value_counts(dropna=False).to_dict(),
 'human_labels':m.stage2_label.value_counts().to_dict(),
 'current_strict':metrics(m.human_strict,m.machine_demand),'current_broad':metrics(m.human_broad,m.machine_demand),
 'crosstab':records(pd.crosstab(m.stage2_label,m.program_demand).reset_index())}
archive=RESEARCH/'archives/pre_current_demand_mainline_20260901/outputs/06_exploratory_attempts/keyword_llm_extraction_attempts'
result['historical_eval']={}
for p in archive.glob('*/summary.json'):
    d=json.loads(p.read_text(encoding='utf-8'))
    result['historical_eval'][p.parent.name]={k:v for k,v in d.items() if k in ['sample_rows','demand_vs_manual_future','manual_stage2_counts']}
claimed_y=pd.Series([1]*66+[0]*15+[1]*3+[0]*259)
claimed_p=pd.Series([1]*81+[0]*262)
result['human']['published_matrix_recomputed']=metrics(claimed_y,claimed_p)

# Exact table grains and presentational limitations.
valid=ag[ag.window_type.notna()]
default=pd.DataFrame(logic.radar())
result['statistics']={'demand_claims':int(claims.program_label.isin(logic.DEMAND_LABELS).sum()),
 'signal_firmyears':len(ag),'signal_firms':int(ag.scode.nunique()),'radar_total':len(valid),
 'radar_unique_firms':int(valid.scode.nunique()),'radar_default_rows':len(default),'radar_default_unique_firms':int(default.scode.nunique()),
 'radar_by_year':valid.groupby('year').size().to_dict(), 'segments':logic.segments(),
 'industry_filter_counts':{i:len(logic.radar(industry=i,limit=100000)) for i in ['光伏','电气设备',None]}}
result['statistics']['pv_counts_by_year']=records(ag[ag.scode.isin(logic.industry_tags()['pv'])].groupby('year').agg(firms=('scode','nunique'),deploy=('n_deploy','sum'),intent=('n_intent','sum')).reset_index())
pvfile=RESEARCH/'outputs/01_demand_construction/03_photovoltaic_text_label_run/classified_all.csv'
pvsource=pd.read_csv(pvfile,usecols=['scode','year'],dtype={'scode':str})
result['pv_existing_run']={'chunks':len(pvsource),'firms':int(pvsource.scode.nunique()),'firmyears':len(pvsource.drop_duplicates()),'new_codes_vs_main':sorted(set(pvsource.scode.str.zfill(6))-set(panel.scode))}
result['country_dictionary_count']=len(logic.rules()['countries']['countries'])

# Year checks: inspect all demand observations using source table keys, plus concrete runtime examples.
panel_keys=set(zip(panel.scode,panel.year))
result['year_checks']={'signal_keys_without_panel':records(ag.loc[[ (c,y) not in panel_keys for c,y in zip(ag.scode,ag.year)],['scode','year']])}
future_cases=[]
textcust=claims[claims.execution_anchor_type.eq('named_customer')]
for code,yr in valid[['scode','year']].itertuples(index=False,name=None):
    chosen=textcust[textcust.scode.eq(code)].drop_duplicates('execution_anchor').head(3)
    for r in chosen[chosen.year.gt(yr)].itertuples():
        future_cases.append({'scode':code,'selected_year':int(yr),'claim_year':int(r.year),'chunk_id':r.chunk_id,'anchor':r.execution_anchor})
f=pd.DataFrame(future_cases)
save_csv(f,'future_text_customer_candidates.csv')
result['year_checks']['future_customer_candidate_rows']=len(f)
result['year_checks']['affected_company_years']=len(f[['scode','selected_year']].drop_duplicates()) if len(f) else 0
result['year_checks']['future_examples']=records(f.head(5))
year_examples=[]
for code,yr in [('002860',2018),('002860',2023),('002860',2017)]:
    d=logic.company_detail(code,yr); ch=logic.chain(code,yr); b=logic.briefing(code,yr)
    year_examples.append({'scode':code,'requested':yr,'detail_year':d['year'],'assets':d['assets'],
     'panel_status':d['panel_status'],'capability_grade':d['capability']['grade'],
     'chain_year':ch['year'] if ch else None,'briefing_year':b['year'] if b else None,
     'signal_years':sorted({x['year'] for x in d['signals']}),'history_years':d['history']['years']})
result['year_checks']['runtime_examples']=year_examples
result['year_checks']['actual_future_text_nodes_000049_2019']=logic.supply_chain('000049',2019)['nodes']

# Capability: reproduce pooled and same-year percentiles; only reference population changes.
cc=sc.concentration()
scorebase=panel.merge(cc[['scode','year','CustomerConcentration']],on=['scode','year'],how='left',validate='one_to_one')
dims=logic.rules()['scoring']['dimensions']
def score_population(byyear):
    sums=pd.Series(0.0,index=scorebase.index); weights=pd.Series(0.0,index=scorebase.index)
    for d in dims:
        field='CustomerConcentration' if d.get('table')=='sc' else d['field']
        raw=scorebase[field]
        reference=cc if d.get('table')=='sc' else panel
        def rankrow(row):
            val=row[field]
            if pd.isna(val):return float('nan')
            pop=reference[reference.year.eq(row.year)][field].dropna() if byyear else reference[field].dropna()
            if pop.empty:return float('nan')
            v=float(pop.le(val).mean())
            return 1-v if d['direction']==-1 else v
        vals=scorebase.apply(rankrow,axis=1)
        sums += vals.fillna(0)*d['weight']; weights += vals.notna()*d['weight']
    return (sums/weights.replace(0,float('nan'))).round(3)
scorebase['pooled_score']=score_population(False)
scorebase['same_year_score']=score_population(True)
grade=lambda x:'待核实' if pd.isna(x) else ('就绪' if x>=.7 else ('蓄力' if x>=.4 else '薄弱'))
scorebase['pooled_grade']=scorebase.pooled_score.map(grade);scorebase['same_year_grade']=scorebase.same_year_score.map(grade)
scorebase['abs_difference']=(scorebase.same_year_score-scorebase.pooled_score).abs()
save_csv(scorebase[['scode','year','pooled_score','same_year_score','pooled_grade','same_year_grade','abs_difference']],'capability_reference_comparison.csv')
result['capability']={'dimensions':len(dims),'weight_sum':sum(d['weight'] for d in dims),
 'effective_weights':{d['key']:d['weight']/sum(x['weight'] for x in dims) for d in dims},
 'grade_changes_if_same_year':int(scorebase.pooled_grade.ne(scorebase.same_year_grade).sum()),
 'max_score_difference':float(scorebase.abs_difference.max()),'largest_examples':records(scorebase.sort_values('abs_difference',ascending=False)[['scode','year','pooled_score','same_year_score','pooled_grade','same_year_grade']].head(5)),
 'customer_concentration_median_pooled':float(cc.CustomerConcentration.median()),
 'customer_concentration_median_by_year':cc.groupby('year').CustomerConcentration.median().to_dict(),
 'runtime_match_examples':[{'scode':c,'year':int(y),'actual':logic.capability_score(c,int(y))['score'],'reproduced':float(scorebase.loc[scorebase.scode.eq(c)&scorebase.year.eq(y),'pooled_score'].iloc[0])} for c,y in [('002860',2023),('002860',2018)]]}

# Supply-chain scope. Anonymous counts are a transparent name-pattern heuristic, not entity adjudication.
result['supply']={}
for name,df in [('sale',sc.top5_sale()),('purchase',sc.top5_purchase())]:
    anon=df['name'].fillna('').str.contains(r'^(?:客户|供应商|第[一二三四五六七八九十0-9]+大?客户|第[一二三四五六七八九十0-9]+大?供应商)',regex=True)
    result['supply'][name]={'rows':len(df),'firms':int(df.scode.nunique()),'anonymous_name_prefix_rows':int(anon.sum()),
     'overseas_name_hit_rows':int(df.overseas.sum()),'overseas_name_hit_firms':int(df.loc[df.overseas,'scode'].nunique()),
     'overseas_name_examples':df.loc[df.overseas,'name'].unique().tolist()[:12]}
result['supply']['network']={'rows':len(sc.network()),'firms':int(sc.network().scode.nunique())}
result['supply']['text_customer_claims']=len(textcust)
result['supply']['text_customer_labels']=textcust.program_label.value_counts().to_dict()
result['supply']['text_customer_time_states']=textcust.time_state.value_counts().to_dict()
result['supply']['false_overseas_name_example']={'name':'上海顺斯德国际贸易有限公司','geo_result':geo_extract('上海顺斯德国际贸易有限公司')}

paths=[APP/'server/logic.py',APP/'server/sc.py',APP/'server/main.py',APP/'web/assets/app.js',APP/'kb/kb-2023.sqlite',APP/'kb/kb-sc-2023.sqlite',human_path,RUN/'classified_all.csv']
result['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
# JSON round-trip through pandas handles NaN keys/values in diagnostic count dictionaries.
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,list):return [clean(v) for v in x]
    if isinstance(x,float) and pd.isna(x):return None
    if hasattr(x,'item'):return x.item()
    return x
result=clean(result)
(OUT/'audit_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({k:result[k] for k in ['windows','human','statistics','year_checks','capability','supply']},ensure_ascii=False,indent=2))
