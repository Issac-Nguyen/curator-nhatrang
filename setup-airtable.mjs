import { readFileSync, writeFileSync } from 'fs';

const env = readFileSync('.env', 'utf8');
const TOKEN = env.match(/AIRTABLE_TOKEN=(.+)/)?.[1]?.trim();

if (!TOKEN) { console.error('No AIRTABLE_TOKEN found in .env'); process.exit(1); }

const headers = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' };

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function api(method, path, body) {
  const url = `https://api.airtable.com${path}`;
  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(`API ${res.status} ${path}: ${data.error?.message || JSON.stringify(data)}`);
  await sleep(250);
  return data;
}

const WORKSPACE_ID = 'wspVr2MonCwhSmJIU';

// ===== Step 1: Find or create base =====
console.log('\n=== Bước 1: Base ===');
const basesData = await api('GET', '/v0/meta/bases');
let base = basesData.bases?.find(b => b.name === 'Nha Trang Curator');

if (!base) {
  console.log('Tạo base mới...');
  const created = await api('POST', '/v0/meta/bases', {
    name: 'Nha Trang Curator',
    workspaceId: WORKSPACE_ID,
    tables: [{ name: 'Sources', fields: [{ name: 'Name', type: 'singleLineText' }] }],
  });
  base = { id: created.id, name: created.name };
  console.log(`Created: ${base.name} (${base.id})`);
} else {
  console.log(`Existing: ${base.name} (${base.id})`);
}

const baseId = base.id;

// ===== Step 2: Get current tables =====
const tablesRes = await api('GET', `/v0/meta/bases/${baseId}/tables`);
let tables = tablesRes.tables;
const tbl = (name) => tables.find(t => t.name === name);

// ===== Step 3: Setup Sources table =====
console.log('\n=== Sources table ===');
let sourcesTable = tbl('Sources');

if (!sourcesTable) {
  sourcesTable = await api('POST', `/v0/meta/bases/${baseId}/tables`, {
    name: 'Sources',
    fields: [
      { name: 'Name', type: 'singleLineText' },
      { name: 'Type', type: 'singleSelect', options: { choices: [{ name: 'RSS' }, { name: 'Facebook' }, { name: 'TikTok' }, { name: 'Instagram' }, { name: 'Website' }] } },
      { name: 'URL', type: 'url' },
      { name: 'Category', type: 'singleSelect', options: { choices: [{ name: 'Sự kiện' }, { name: 'Địa điểm' }, { name: 'Tin tức' }, { name: 'Workshop' }, { name: 'Ẩm thực' }] } },
      { name: 'Active', type: 'checkbox', options: { color: 'greenBright', icon: 'check' } },
      { name: 'Last checked', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
      { name: 'Notes', type: 'multilineText' },
    ],
  });
  console.log(`Created Sources: ${sourcesTable.id}`);
} else {
  console.log(`Existing Sources: ${sourcesTable.id}`);
  // Add any missing fields
  const existing = sourcesTable.fields.map(f => f.name);
  const toAdd = [
    { name: 'Type', type: 'singleSelect', options: { choices: [{ name: 'RSS' }, { name: 'Facebook' }, { name: 'TikTok' }, { name: 'Instagram' }, { name: 'Website' }] } },
    { name: 'URL', type: 'url' },
    { name: 'Category', type: 'singleSelect', options: { choices: [{ name: 'Sự kiện' }, { name: 'Địa điểm' }, { name: 'Tin tức' }, { name: 'Workshop' }, { name: 'Ẩm thực' }] } },
    { name: 'Active', type: 'checkbox', options: { color: 'greenBright', icon: 'check' } },
    { name: 'Last checked', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
    { name: 'Notes', type: 'multilineText' },
  ];
  for (const f of toAdd) {
    if (!existing.includes(f.name)) {
      await api('POST', `/v0/meta/bases/${baseId}/tables/${sourcesTable.id}/fields`, f);
      console.log(`  + ${f.name}`);
    } else {
      console.log(`  skip ${f.name} (exists)`);
    }
  }
  // Refresh
  const r = await api('GET', `/v0/meta/bases/${baseId}/tables`);
  tables = r.tables;
  sourcesTable = tbl('Sources');
}

// ===== Step 4: Raw Items table =====
console.log('\n=== Raw Items table ===');
let rawTable = tbl('Raw Items');

if (!rawTable) {
  rawTable = await api('POST', `/v0/meta/bases/${baseId}/tables`, {
    name: 'Raw Items',
    fields: [
      { name: 'Title', type: 'singleLineText' },
      { name: 'Content', type: 'multilineText' },
      { name: 'Source', type: 'multipleRecordLinks', options: { linkedTableId: sourcesTable.id } },
      { name: 'URL', type: 'url' },
      { name: 'Published date', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
      { name: 'Collected at', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
      { name: 'AI Summary', type: 'multilineText' },
      { name: 'Status', type: 'singleSelect', options: { choices: [{ name: 'New' }, { name: 'Reviewed' }, { name: 'Use' }, { name: 'Skip' }] } },
    ],
  });
  console.log(`Created Raw Items: ${rawTable.id}`);
  tables = (await api('GET', `/v0/meta/bases/${baseId}/tables`)).tables;
  rawTable = tbl('Raw Items');
} else {
  console.log(`Existing Raw Items: ${rawTable.id}`);
}

// ===== Step 5: Content Queue table =====
console.log('\n=== Content Queue table ===');
let cqTable = tbl('Content Queue');

if (!cqTable) {
  cqTable = await api('POST', `/v0/meta/bases/${baseId}/tables`, {
    name: 'Content Queue',
    fields: [
      { name: 'Title', type: 'singleLineText' },
      { name: 'Raw Item', type: 'multipleRecordLinks', options: { linkedTableId: rawTable.id } },
      { name: 'Content type', type: 'singleSelect', options: { choices: [{ name: 'Carousel' }, { name: 'TikTok' }, { name: 'Newsletter' }, { name: 'Both' }] } },
      { name: 'Draft VN', type: 'multilineText' },
      { name: 'Draft EN', type: 'multilineText' },
      { name: 'Final VN', type: 'multilineText' },
      { name: 'Final EN', type: 'multilineText' },
      { name: 'Schedule date', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
      { name: 'Platform', type: 'multipleSelects', options: { choices: [{ name: 'TikTok VN' }, { name: 'TikTok EN' }, { name: 'Instagram VN' }, { name: 'Instagram EN' }, { name: 'Newsletter' }] } },
      { name: 'Affiliate link', type: 'url' },
      { name: 'Status', type: 'singleSelect', options: { choices: [{ name: 'Draft' }, { name: 'Editing' }, { name: 'Approved' }, { name: 'Scheduled' }, { name: 'Done' }] } },
    ],
  });
  console.log(`Created Content Queue: ${cqTable.id}`);
  tables = (await api('GET', `/v0/meta/bases/${baseId}/tables`)).tables;
  cqTable = tbl('Content Queue');
} else {
  console.log(`Existing Content Queue: ${cqTable.id}`);
}

// ===== Step 6: Published table =====
console.log('\n=== Published table ===');
let pubTable = tbl('Published');

if (!pubTable) {
  pubTable = await api('POST', `/v0/meta/bases/${baseId}/tables`, {
    name: 'Published',
    fields: [
      { name: 'Title', type: 'singleLineText' },
      { name: 'Content Queue Item', type: 'multipleRecordLinks', options: { linkedTableId: cqTable.id } },
      { name: 'Platform', type: 'singleSelect', options: { choices: [{ name: 'TikTok VN' }, { name: 'TikTok EN' }, { name: 'Instagram VN' }, { name: 'Instagram EN' }, { name: 'Newsletter' }] } },
      { name: 'Post URL', type: 'url' },
      { name: 'Published at', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'Asia/Ho_Chi_Minh' } },
      { name: 'Views', type: 'number', options: { precision: 0 } },
      { name: 'Likes', type: 'number', options: { precision: 0 } },
      { name: 'Comments', type: 'number', options: { precision: 0 } },
      { name: 'Saves', type: 'number', options: { precision: 0 } },
      { name: 'Affiliate clicks', type: 'number', options: { precision: 0 } },
      { name: 'Affiliate revenue', type: 'currency', options: { precision: 0, symbol: '₫' } },
      { name: 'Notes', type: 'multilineText' },
    ],
  });
  console.log(`Created Published: ${pubTable.id}`);
  tables = (await api('GET', `/v0/meta/bases/${baseId}/tables`)).tables;
  pubTable = tbl('Published');
} else {
  console.log(`Existing Published: ${pubTable.id}`);
}

// ===== Step 7: Seed Sources data =====
console.log('\n=== Seed data: Sources ===');
const existingRecs = await api('GET', `/v0/${baseId}/Sources`);
const existingNames = (existingRecs.records || []).map(r => r.fields?.Name);
console.log('Existing records:', existingNames);

const seeds = [
  { Name: 'Báo Khánh Hoà', Type: 'RSS', URL: 'https://baokhanhhoa.vn/rss', Category: 'Tin tức', Active: true },
  { Name: 'Nhà Hát Đó', Type: 'Facebook', URL: 'https://facebook.com/lifepuppets.show', Category: 'Sự kiện', Active: true },
  { Name: 'Louisiane Brewhouse', Type: 'Facebook', URL: 'https://facebook.com/lousianebrewhousenhatrang', Category: 'Sự kiện', Active: true },
  { Name: 'Sailing Club Nha Trang', Type: 'Facebook', URL: 'https://facebook.com/sailingclubnhatrang', Category: 'Sự kiện', Active: true },
  { Name: 'HK Club Nha Trang', Type: 'Facebook', URL: 'https://facebook.com/havanaclubnhatrang', Category: 'Sự kiện', Active: true },
  { Name: 'Bối Art', Type: 'Facebook', URL: 'https://facebook.com/boiart.vetranhthugian', Category: 'Workshop', Active: true },
  { Name: 'Ticketbox Nha Trang', Type: 'Website', URL: 'https://ticketbox.vn', Category: 'Sự kiện', Active: true },
  { Name: 'VinWonders Nha Trang', Type: 'Facebook', URL: 'https://facebook.com/VinWonders.NhaTrang.Official', Category: 'Sự kiện', Active: true },
];

for (const s of seeds) {
  if (existingNames.includes(s.Name)) { console.log(`  skip: ${s.Name}`); continue; }
  await api('POST', `/v0/${baseId}/Sources`, { records: [{ fields: s }] });
  console.log(`  + ${s.Name}`);
}

// ===== Save config =====
const finalTables = (await api('GET', `/v0/meta/bases/${baseId}/tables`)).tables;
const tableMap = Object.fromEntries(finalTables.map(t => [t.name, t.id]));

const config = {
  baseId,
  baseName: 'Nha Trang Curator',
  workspaceId: WORKSPACE_ID,
  tables: {
    sources: tableMap['Sources'],
    rawItems: tableMap['Raw Items'],
    contentQueue: tableMap['Content Queue'],
    published: tableMap['Published'],
  },
  apiEndpoints: {
    sources: `https://api.airtable.com/v0/${baseId}/Sources`,
    rawItems: `https://api.airtable.com/v0/${baseId}/Raw%20Items`,
    contentQueue: `https://api.airtable.com/v0/${baseId}/Content%20Queue`,
    published: `https://api.airtable.com/v0/${baseId}/Published`,
  },
  testCurl: `curl "https://api.airtable.com/v0/${baseId}/Sources" -H "Authorization: Bearer ${TOKEN}"`,
};

writeFileSync('config.json', JSON.stringify(config, null, 2));

console.log('\n========== HOÀN THÀNH ==========');
console.log(`Base ID: ${baseId}`);
console.log('Table IDs:');
for (const [name, id] of Object.entries(tableMap)) console.log(`  ${name}: ${id}`);
console.log('\nconfig.json saved.');
console.log(`\nTest: curl "https://api.airtable.com/v0/${baseId}/Sources" -H "Authorization: Bearer ${TOKEN}"`);
