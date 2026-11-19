"""Read-only sales dashboard for verified HMRC data stored in Supabase."""
import os
import pandas as pd
import requests
import streamlit as st
from datetime import date

st.set_page_config(page_title='UK Freight Sales Intelligence V5',page_icon='🚢',layout='wide')
st.markdown('''<style>[data-testid="stMetric"]{background:#172b39!important;border:1px solid #446174;border-radius:12px;padding:14px}[data-testid="stMetric"] *{color:#fff!important}</style>''',unsafe_allow_html=True)
st.title('🚢 UK Freight Sales Intelligence · V5 Pilot')
st.caption('Database-backed HMRC published commodity-month evidence. Not shipment counts.')

def credentials():
    try:return st.secrets['SUPABASE_URL'].rstrip('/'),st.secrets['SUPABASE_SECRET_KEY']
    except (KeyError,FileNotFoundError):return os.getenv('SUPABASE_URL','').rstrip('/'),os.getenv('SUPABASE_SECRET_KEY','')

@st.cache_data(ttl=300,show_spinner=False)
def fetch_table(table,fields='*'):
    url,key=credentials()
    if not url or not key:raise RuntimeError('Supabase credentials not configured in Streamlit secrets')
    allrows=[];start=0
    while True:
        r=requests.get(f'{url}/rest/v1/{table}',params={'select':fields,'order':'trader_id.asc','limit':1000,'offset':start},headers={'apikey':key,},timeout=45)
        r.raise_for_status();part=r.json();allrows.extend(part)
        if len(part)<1000:break
        start+=1000
        if start>=100000:raise RuntimeError('Dashboard safety limit reached')
    return pd.DataFrame(allrows)

try:
    traders=fetch_table('traders','trader_id,company_name,postcode,registered_address')
    checks=fetch_table('trader_verification','trader_id,import_status,export_status,last_verified_at')
    evidence=fetch_table('trade_records','trader_id,direction,trade_month,commodity_code')
except Exception as exc:
    st.error(f'Database connection failed: {exc}');st.stop()

if traders.empty:
    st.info('Database is empty. Run the HMRC Collector workflow in GitHub Actions first.');st.stop()
if checks.empty:
    st.warning('No trader activity checks completed. Run the collector first.');st.stop()

complete=checks[(checks['import_status']=='complete')&(checks['export_status']=='complete')]
base=traders.merge(complete[['trader_id','last_verified_at']],on='trader_id',how='inner')
if base.empty:
    st.warning('No fully verified traders yet. Failed or pending traders are not scored.');st.stop()

anchor=st.text_input('Reporting window end (YYYY-MM)',value='2026-09')
try:
    anchor_dt=pd.Timestamp(anchor+'-01')
    start24=anchor_dt-pd.DateOffset(months=23)
    start12=anchor_dt-pd.DateOffset(months=11)
except Exception:st.error('Enter YYYY-MM');st.stop()

if evidence.empty:evidence=pd.DataFrame(columns=['trader_id','direction','trade_month','commodity_code'])
evidence['trade_month']=pd.to_datetime(evidence['trade_month'],errors='coerce')
evidence=evidence[(evidence['trade_month']>=start24)&(evidence['trade_month']<=anchor_dt)]
rows=[]
for r in base.to_dict('records'):
    ev=evidence[evidence['trader_id']==r['trader_id']]
    obj=dict(r)
    for direction in ['Import','Export']:
        part=ev[ev['direction']==direction]
        obj[f'{direction} months 24m']=part['trade_month'].nunique()
        obj[f'{direction} months 12m']=part[part['trade_month']>=start12]['trade_month'].nunique()
        obj[f'Latest {direction.lower()}']=part['trade_month'].max().strftime('%Y-%m') if not part.empty else 'Not observed'
        obj[f'{direction} commodity codes']=', '.join(sorted(part['commodity_code'].dropna().astype(str).unique()))
    active=max(obj['Import months 12m'],obj['Export months 12m'])
    historical=max(obj['Import months 24m'],obj['Export months 24m'])
    obj['Tier']='A' if active>=10 else 'B' if active>=4 else 'C' if active>=1 else 'Historical' if historical else 'No activity observed'
    obj['Sales priority']='High' if obj['Tier']=='A' else 'Medium' if obj['Tier']=='B' else 'Low' if historical else 'Research'
    obj['Trade direction']='Both' if obj['Import months 24m'] and obj['Export months 24m'] else 'Importer' if obj['Import months 24m'] else 'Exporter' if obj['Export months 24m'] else 'None observed'
    obj['HMRC source']=f"https://www.uktradeinfo.com/traders/{'-'.join(''.join(c if c.isalnum() else ' ' for c in r['company_name'].lower()).split())}-{r['trader_id']}"
    rows.append(obj)
df=pd.DataFrame(rows)

col1,col2=st.columns(2)
with col1:mode=st.selectbox('Search by',['Postcode','Company name'])
with col2:query=st.text_input('Postcode prefix or company',value='M1' if mode=='Postcode' else '')
if query.strip():
    if mode=='Postcode':df=df[df['postcode'].fillna('').str.replace(' ','',regex=False).str.upper().str.startswith(query.upper().replace(' ',''))]
    else:df=df[df['company_name'].str.contains(query,case=False,regex=False,na=False)]
verified_only=st.checkbox('Show only traders with published activity in 24 months',value=True)
if verified_only:df=df[(df['Import months 24m']>0)|(df['Export months 24m']>0)]
limit=st.selectbox('Results to display',[25,50,100,250,1000],index=2)
rank={'High':0,'Medium':1,'Low':2,'Research':3}
df=df.assign(_rank=df['Sales priority'].map(rank)).sort_values(['_rank','Import months 12m','Export months 12m'],ascending=[True,False,False]).drop(columns='_rank')
matched=len(df);df=df.head(limit)
a,b,c=st.columns(3);a.metric('Qualified in stored data',matched);b.metric('A-tier displayed',int((df['Tier']=='A').sum()));c.metric('Displayed',len(df))
st.caption(f'Stored directory: {len(traders):,} unique IDs · Fully checked: {len(base):,} · Evidence rows: {len(evidence):,}. This is NOT a complete territory ranking unless collection coverage has been independently verified.')
if df.empty:st.warning('No qualifying traders in the stored, verified subset. This does not establish that the territory has no traders.')
else:
    st.dataframe(df,hide_index=True,use_container_width=True)
    st.download_button('Download sales CSV',df.to_csv(index=False).encode('utf-8-sig'),'hmrc_v5_sales.csv','text/csv',use_container_width=True)
st.warning('PILOT: HMRC postcode API behavior and complete territory discovery remain to be reconciled. Do not use for production account allocation yet.')
