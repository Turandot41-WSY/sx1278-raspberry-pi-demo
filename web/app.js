/* Display only validated packet observations from the local telemetry API. */
const byId = (id) => document.getElementById(id);
function cell(value) {
  const element = document.createElement('td');
  element.textContent = String(value ?? '—');
  return element;
}
function show(data) {
  byId('status').textContent = data.state;
  for (const key of ['received', 'valid', 'invalid']) byId(key).textContent = data[key];
  byId('origin').textContent = `Data origin: ${data.dataOrigin} · Session: ${data.source || 'waiting'}`;
  byId('warning').textContent = data.warning || '';
  const frame = data.activeLatest;
  if (frame) {
    const values = {'Sample':frame.sample, 'Orbit time (seconds)':frame.time, 'Latitude (degrees)':frame.latitude,
      'Longitude (degrees)':frame.longitude, 'Altitude (km)':frame.altitude,
      'Reference match':frame.sourceMatched ? 'Exact payload match' : 'Unverified segment',
      'RSSI / SNR raw':`${frame.rssiRaw} / ${frame.snrRaw}`, 'Frame bytes (hex)':frame.frameHex};
    byId('latest').replaceChildren();
    for (const [key, value] of Object.entries(values)) {
      const term = document.createElement('dt'); term.textContent = key;
      const description = document.createElement('dd'); description.textContent = String(value ?? '—');
      byId('latest').append(term, description);
    }
  }
  byId('rows').replaceChildren();
  for (const frame of data.samples.slice(-20).reverse()) {
    const row = document.createElement('tr');
    for (const value of [frame.sample,frame.trackLabel,frame.latitude,frame.longitude,frame.sourceMatched ? 'Match' : 'Unverified']) row.append(cell(value));
    byId('rows').append(row);
  }
}
async function refresh() {
  try {
    const response = await fetch('/api/telemetry', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    show(await response.json());
  } catch (error) { byId('status').textContent = `Receiver service unavailable: ${error.message}`; }
  setTimeout(refresh, 1000);
}
refresh();
