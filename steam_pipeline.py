# =============================================================================
# Steam Uruguay - Gaming Market Accessibility Analysis
# Author: Franco Ezequiel Cossatti Abalos
# Description: Collection, cleaning and analysis of the Top 1000 Steam games
#              from the Uruguayan market perspective.
# =============================================================================

import requests as rq
import pandas as pd
import time
import re

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
TOP_N            = 1000
OUTPUT_FILE      = 'steamGames_clean.csv'
MINIMUM_WAGE_UYU = 24572

session = rq.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


# =============================================================================
# STEP 1: SteamSpy — full catalog
# Downloads all available games by paginating 1000 at a time.
# We use CCU (Concurrent Users) as the popularity metric.
# =============================================================================
print("=" * 60)
print("STEP 1: Downloading SteamSpy catalog...")
print("=" * 60)

pages = []

for i in range(0, 100):
    time.sleep(1.5)
    try:
        r = session.get(
            f"https://steamspy.com/api.php?request=all&page={i}",
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            print(f"End of catalog at page {i}.")
            break
        pages.append(pd.DataFrame.from_dict(data, orient='index'))
        print(f"  Page {i}: {len(data)} games downloaded")
    except Exception as e:
        print(f"  Error on page {i}: {e}")

df_spy = pd.concat(pages)
df_spy.index = df_spy.index.astype(int)
df_spy['ccu'] = pd.to_numeric(df_spy['ccu'], errors='coerce').fillna(0)


# =============================================================================
# STEP 2: Filter Top N by CCU
# We only call the Steam API for the most relevant games,
# avoiding thousands of unnecessary requests.
# =============================================================================
print(f"\nSelecting Top {TOP_N} games by CCU...")

df_top = df_spy.nlargest(TOP_N, 'ccu')[['ccu', 'owners', 'positive', 'negative']]
print(f"  CCU min: {int(df_top['ccu'].min())} | CCU max: {int(df_top['ccu'].max())}")


# =============================================================================
# STEP 3: Steam Store API — fresh data with prices in UYU
# cc=uy returns up-to-date prices in Uruguayan pesos.
# We flatten nested fields to simplify later analysis.
# =============================================================================
print(f"\n{'=' * 60}")
print(f"STEP 3: Downloading Steam Store data for {TOP_N} games...")
print(f"  Estimated time: ~25 minutes")
print(f"{'=' * 60}")

results = []

for i, app_id in enumerate(df_top.index.tolist()):
    time.sleep(1.5)
    try:
        r = session.get(
            f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=uy&l=english",
            timeout=30
        )
        r.raise_for_status()
        body = r.json().get(str(app_id), {})
    except Exception as e:
        print(f"  Error on appid {app_id}: {e}")
        continue

    if not (body.get('success') and body.get('data')):
        continue

    d = body['data']

    # Flatten price_overview — the API returns prices in cents
    price_overview = d.get('price_overview', {})

    results.append({
        'appid':               app_id,
        'name':                d.get('name'),
        'type':                d.get('type'),
        'is_free':             d.get('is_free'),
        'price_uyu':           price_overview.get('final', 0) / 100,
        'original_price_uyu':  price_overview.get('initial', 0) / 100,
        'discount_pct':        price_overview.get('discount_percent', 0),
        'release_date':        d.get('release_date', {}).get('date'),
        'supported_languages': d.get('supported_languages'),
        'metacritic_score':    d.get('metacritic', {}).get('score'),
        'genres':              ','.join(g['description'] for g in d.get('genres', [])),
        'categories':          ','.join(c['description'] for c in d.get('categories', [])),
        'platforms_windows':   d.get('platforms', {}).get('windows'),
        'platforms_mac':       d.get('platforms', {}).get('mac'),
        'platforms_linux':     d.get('platforms', {}).get('linux'),
        'min_requirements':    d.get('pc_requirements', {}).get('minimum', ''),
        'developers':          ','.join(d.get('developers', [])),
        'publishers':          ','.join(d.get('publishers', [])),
    })

    if (i + 1) % 100 == 0:
        print(f"  Progress: [{i+1}/{TOP_N}] games processed")


# =============================================================================
# STEP 4: Merge — combine SteamSpy data with Steam Store data
# =============================================================================
print(f"\n{'=' * 60}")
print("STEP 4: Combining data sources...")
print(f"{'=' * 60}")

df_steam = pd.DataFrame(results)

df = df_top.reset_index().rename(columns={'index': 'appid'}).merge(
    df_steam, on='appid', how='inner'
)
print(f"  Games with complete data: {len(df)}")


# =============================================================================
# STEP 5: Data cleaning
# =============================================================================
print(f"\n{'=' * 60}")
print("STEP 5: Cleaning data...")
print(f"{'=' * 60}")

# Data types
df['positive']         = pd.to_numeric(df['positive'], errors='coerce')
df['negative']         = pd.to_numeric(df['negative'], errors='coerce')
df['release_date']     = pd.to_datetime(df['release_date'], errors='coerce')
df['metacritic_score'] = pd.to_numeric(df['metacritic_score'], errors='coerce')
df['discount_pct']     = pd.to_numeric(df['discount_pct'], errors='coerce').fillna(0).astype(int)

# Drop corrupted rows from merge (non-numeric appid)
df = df[df['appid'].astype(str).str.match(r'^\d+$')]

# Strip HTML from min_requirements
def clean_html(text):
    if pd.isna(text) or not text:
        return None
    return re.sub(r'<[^>]+>', ' ', text).strip()

df['min_requirements'] = df['min_requirements'].apply(clean_html)

# Clean characters that break CSV formatting
text_cols = ['min_requirements', 'supported_languages', 'genres', 'categories', 'developers', 'publishers', 'name']
for col in text_cols:
    df[col] = df[col].astype(str).str.replace('\n', ' ').str.replace('\r', ' ').str.replace('"', "'")

print(f"  Rows after cleaning: {len(df)}")


# =============================================================================
# STEP 6: Derived columns
# All calculated metrics for the analysis and dashboard.
# =============================================================================
print(f"\n{'=' * 60}")
print("STEP 6: Creating derived columns...")
print(f"{'=' * 60}")

# Review score: proportion of positive reviews (0 to 1)
df['review_score'] = (df['positive'] / (df['positive'] + df['negative'])).round(4)

# Language support
df['has_es_latam'] = df['supported_languages'].str.contains('Spanish - Latin America', na=False)

# Game classification
df['is_indie']        = df['genres'].str.contains('Indie', na=False)
df['is_multiplayer']  = df['categories'].str.contains('Multi-player', na=False)
df['is_singleplayer'] = df['categories'].str.contains('Single-player', na=False)

# Economic accessibility
df['pct_min_wage'] = (df['price_uyu'] / MINIMUM_WAGE_UYU * 100).round(2)

# Time variables
df['year']      = df['release_date'].dt.year.astype('Int64')
df['age_years'] = ((pd.Timestamp.now() - df['release_date']).dt.days / 365).round(1)
df['era'] = pd.cut(
    df['age_years'],
    bins=[0, 2, 5, 10, float('inf')],
    labels=['Recent', 'Modern', 'Established', 'Classic']
)

# Hardware requirements (extracted with regex)
df['ram_gb'] = df['min_requirements'].apply(
    lambda x: int(m.group(1))
    if pd.notna(x) and (m := re.search(r'(\d+)\s*GB\s*RAM', x, re.I))
    else None
)
df['storage_gb'] = df['min_requirements'].apply(
    lambda x: int(m.group(1))
    if pd.notna(x) and (m := re.search(r'(\d+)\s*GB\s*available', x, re.I))
    else None
)


# =============================================================================
# STEP 7: Export final CSV
# =============================================================================
print(f"\n{'=' * 60}")
print("STEP 7: Saving CSV...")
print(f"{'=' * 60}")

df.to_csv(OUTPUT_FILE, index=False, quoting=1)
print(f"  File saved: {OUTPUT_FILE}")
print(f"  Rows: {len(df)} | Columns: {len(df.columns)}")


# =============================================================================
# STEP 8: Analysis summary
# The 11 key insights of the project.
# =============================================================================
print(f"\n{'=' * 60}")
print("STEP 8: Analysis summary")
print(f"{'=' * 60}")

df_paid = df[~df['is_free'] & (df['price_uyu'] > 0)]

print(f"\n1. Median price (UYU):            {df_paid['price_uyu'].median():.0f}")
print(f"   % of minimum wage:              {df_paid['price_uyu'].median() / MINIMUM_WAGE_UYU * 100:.1f}%")

print(f"\n2. Free games:                    {df['is_free'].sum()} ({df['is_free'].mean()*100:.1f}%)")

print(f"\n3. With Latin American Spanish:   {df['has_es_latam'].sum()} ({df['has_es_latam'].mean()*100:.1f}%)")

print(f"\n4. Price-review correlation:      {df_paid[['price_uyu','review_score']].corr().iloc[0,1]:.2f}")

print(f"\n5. Indie — median review score:   {df[df['is_indie']]['review_score'].median():.3f}")
print(f"   AAA  — median review score:     {df[~df['is_indie']]['review_score'].median():.3f}")

print(f"\n6. Games with discount:           {(df['discount_pct'] > 0).sum()} ({(df['discount_pct'] > 0).mean()*100:.1f}%)")
print(f"   Median discount:                {df[df['discount_pct'] > 0]['discount_pct'].median():.0f}%")

print(f"\n7. Linux support:                 {df['platforms_linux'].sum()} ({df['platforms_linux'].mean()*100:.1f}%)")

print(f"\n8. RAM 90th percentile:           {df['ram_gb'].quantile(0.9):.0f} GB")
print(f"   Storage 90th percentile:        {df['storage_gb'].quantile(0.9):.0f} GB")

print(f"\n9. Median CCU — Multiplayer:      {df[df['is_multiplayer']]['ccu'].median():.0f}")
print(f"   Median CCU — Singleplayer:      {df[df['is_singleplayer']]['ccu'].median():.0f}")

classics = df[df['age_years'] >= 10]
recent   = df[df['age_years'] < 2]
print(f"\n10. Median price — classics:      {classics['price_uyu'].median():.0f} UYU")
print(f"    Median price — recent:         {recent['price_uyu'].median():.0f} UYU")
print(f"    Median review — classics:      {classics['review_score'].median():.3f}")
print(f"    Median review — recent:        {recent['review_score'].median():.3f}")

print(f"\n{'=' * 60}")
print("Analysis complete.")
print(f"{'=' * 60}")