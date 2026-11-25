import {display,esc} from '../../utils/html.js';
import {table} from './table.js';

function chart(spec) {
  const points = (spec?.points || []).filter(point => Number.isFinite(point.value)).slice(0,12);
  if (!points.length) return '';
  const max = Math.max(...points.map(point => Math.abs(point.value)), 1e-9);
  return `<figure><figcaption>${esc(spec.label)} ${spec.unit ? `· ${esc(spec.unit)}` : ''}</figcaption>${points.map(point => {
    const proportion = Math.abs(point.value) / max * 47;
    const start = point.value < 0 ? 50 - proportion : 50;
    return `<div class="chart-row"><span>${esc(point.label)}</span><div class="chart-track"><i style="inset-inline-start:${start}%;width:${proportion}%"></i></div><strong>${esc(display(point.value))}</strong></div>`;
  }).join('')}</figure>`;
}

function sensitivity(spec) {
  if (!spec) return '';
  if (!spec.applicable) return `<h3>逐台剔除复核</h3><p class="hint">${esc(spec.note)}</p>`;
  const metrics = [['全量联查首位',spec.baseline_top],['复核机组',spec.total],['首位保持',spec.held],['首位易主',spec.changed.length],['缺数未出结论',spec.missing.length]];
  const rows = spec.rounds.map(round => ({
    机组:round.asset_id,
    剔除机组日:round.removed_days,
    剔除监测小时:round.removed_hours,
    本轮首位:round.top ?? '—',
    结论:round.verdict === '首位易主' ? `⚠ 首位易主 → ${round.top}` : round.verdict,
    缺数原因:round.reason || '—',
    各告警复算:round.alarms.map(entry => entry.ratio === null ? `${entry.alarm}：${entry.reason}` : `${entry.alarm}：${entry.ratio}`).join('；'),
  }));
  return `<h3>逐台剔除复核</h3><p>${esc(spec.headline)}</p><dl class="metrics">${metrics.map(([key,value]) => `<div><dt>${esc(key)}</dt><dd>${esc(display(value))}</dd></div>`).join('')}</dl>${table(rows)}<p class="hint">${esc(spec.method)}</p>`;
}

export function report(result) {
  const metrics = (result.metric_order || Object.keys(result.metrics)).map(key => [key,result.metrics[key]]);
  const columns = result.columns?.map(key => ({key,label:key}));
  return `<div class="reading"><h2>${esc(result.headline)}</h2><dl class="metrics">${metrics.map(([key,value]) => `<div><dt>${esc(key)}</dt><dd>${esc(display(value))}</dd></div>`).join('')}</dl>${chart(result.chart)}<h3>业务明细</h3>${table(result.rows,columns)}${sensitivity(result.sensitivity)}<h3>口径与限制</h3><ul>${result.notes.map(note => `<li>${esc(note)}</li>`).join('')}</ul></div>`;
}
