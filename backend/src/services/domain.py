from dataclasses import dataclass
from datetime import date


COALARMS = ('冷凝水流量低', '压缩机电流偏高', '冷冻水压差低')
LOAD_BANDS = ('低负荷', '高负荷')
NO_COALARM = '无'


@dataclass
class Exposure:
    minutes: int = 0
    events: int = 0

    @property
    def rate(self) -> float | None:
        return self.events * 60_000 / self.minutes if self.minutes else None


def sample_rows() -> list[dict]:
    patterns = (
        ((1, 0, 0, 0, 0, 0, 0, 0), (2, 0, 1, 0, 1, 1, 0, 0)),
        ((1, 0, 0, 0, 1, 0, 0, 0), (2, 0, 1, 0, 1, 1, 1, 0)),
    )
    rows = []
    for room_index, room in enumerate(('东站机房', '西站机房')):
        for load_index, load_band in enumerate(LOAD_BANDS):
            for index in range(24):
                alarms = []
                if index < (8, 16)[load_index]:
                    alarms.append(COALARMS[0])
                if index % 2 == 0:
                    alarms.append(COALARMS[1])
                if index < 2:
                    alarms.append(COALARMS[2])
                rows.append({
                    'asset_id': f'CH-{room_index + 1}{index % 8 + 1:02d}',
                    'service_date': date(2026, 10, 12 + load_index * 3 + index // 8).isoformat(),
                    'room': room,
                    'load_band': load_band,
                    'runtime_minutes': (360, 480, 600, 720)[index % 4],
                    'coalarms': '|'.join(alarms) or NO_COALARM,
                    'target_events': patterns[room_index][load_index][index % 8],
                })
    return rows


def _integer_option(options: dict, key: str, default: int, maximum: int, label: str) -> int:
    value = options.get(key, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'请把{label}填为 1–{maximum} 之间的整数。')
    return value


def _group_exposure(rows: list[dict]) -> dict:
    grouped = {alarm: {} for alarm in COALARMS}
    seen = set()
    for line, row in enumerate(rows, start=2):
        asset = row['asset_id']
        service_date = row['service_date']
        room = row['room']
        load = row['load_band']
        minutes = row['runtime_minutes']
        events = row['target_events']
        if not asset.strip() or not room.strip():
            raise ValueError(f'CSV 第 {line} 行请补齐机组编号和机房。')
        try:
            if date.fromisoformat(service_date).isoformat() != service_date:
                raise ValueError
        except ValueError as error:
            raise ValueError(f'CSV 第 {line} 行请按 YYYY-MM-DD 填写有效运行日期。') from error
        if (asset, service_date) in seen:
            raise ValueError(f'CSV 第 {line} 行机组 {asset} 在 {service_date} 重复，请核对并保留一条日记录。')
        seen.add((asset, service_date))
        if load not in LOAD_BANDS:
            raise ValueError(f'CSV 第 {line} 行请将计划负荷填写为低负荷或高负荷。')
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ValueError(f'CSV 第 {line} 行请填写 1–1440 的有效监测运行分钟。')
        if type(events) is not int or not 0 <= events <= minutes * 60:
            raise ValueError(f'CSV 第 {line} 行请按监测期内去重后的新发事件填写非负整数，最多每秒一次。')
        alarms = [label.strip() for label in row['coalarms'].split('|')]
        present = set(alarms)
        if present == {NO_COALARM} and len(alarms) == 1:
            present.clear()
        elif len(present) != len(alarms) or not present.issubset(COALARMS):
            raise ValueError(f'CSV 第 {line} 行请用 | 分隔告警目录中的不同告警，确认全无时单独填写“无”。')
        stratum = (room, load)
        for alarm, strata in grouped.items():
            if stratum not in strata:
                strata[stratum] = (Exposure(), Exposure())
            exposed, comparison = strata[stratum]
            arm = exposed if alarm in present else comparison
            arm.minutes += minutes
            arm.events += events
    return grouped


def _support(exposed: Exposure, comparison: Exposure, min_minutes: int, min_events: int) -> str:
    if not exposed.minutes or not comparison.minutes:
        return '缺少有告警组或无告警组的监测时间'
    if min(exposed.minutes, comparison.minutes) < min_minutes:
        return '至少一组未达到最低监测小时'
    if exposed.events + comparison.events < min_events:
        return '两组合计未达到最低目标事件数'
    return ''


def _round(value: float | None) -> float | None:
    return float(f'{value:.6g}') if value is not None else None


def _interpret(ratio: float) -> str:
    if ratio > 1:
        return '有告警组发生率较高'
    if ratio < 1:
        return '有告警组发生率较低'
    return '两组发生率在展示精度内相同'


def _result_row(alarm, scope, stratum, support, exposed, comparison, rates, ratio, crude_ratio, status):
    return {
        '伴随告警': alarm,
        '比较口径': scope,
        '机房与计划负荷': stratum,
        '达标层数 / 总层数': support,
        '有告警监测小时': _round(exposed.minutes / 60),
        '无告警监测小时': _round(comparison.minutes / 60),
        '有告警目标事件数': exposed.events,
        '无告警目标事件数': comparison.events,
        '有告警发生率（次/千小时）': _round(rates[0]),
        '无告警发生率（次/千小时）': _round(rates[1]),
        '率比': ratio,
        '达标层粗率比': crude_ratio,
        '支持与解读': status,
    }


def _eligibility(strata, min_minutes, min_events):
    return [
        (key, exposed, comparison, _support(exposed, comparison, min_minutes, min_events))
        for key, (exposed, comparison) in sorted(strata.items())
    ]


def _analyze_alarm(alarm, strata, min_minutes, min_events):
    details = []
    eligible = []
    for (room, load), exposed, comparison, reason in _eligibility(strata, min_minutes, min_events):
        ratio = None
        if reason:
            status = reason
        else:
            eligible.append(((room, load), exposed, comparison))
            if comparison.events:
                ratio = _round(exposed.rate / comparison.rate)
                status = f'达到分层门槛，{_interpret(ratio)}'
            else:
                status = '达到分层门槛，对照事件为零，层内率比未定义'
        details.append(_result_row(
            alarm, '层内观察', f'{room} / {load}', None, exposed, comparison,
            (exposed.rate, comparison.rate), ratio, None, status,
        ))

    exposed_total = Exposure(sum(a.minutes for _, a, _ in eligible), sum(a.events for _, a, _ in eligible))
    comparison_total = Exposure(sum(b.minutes for _, _, b in eligible), sum(b.events for _, _, b in eligible))
    total_minutes = exposed_total.minutes + comparison_total.minutes
    crude_ratio = (
        _round(exposed_total.rate / comparison_total.rate) if comparison_total.events else None
    )
    rates = (None, None)
    ratio = None
    plan = None
    if len(eligible) < 2:
        status = '共同达标层少于两层，请补齐同层有无告警记录后复算'
    else:
        # Apply one exposure distribution to both arms, using combined runtime in each eligible stratum.
        rates = (
            sum((a.minutes + b.minutes) * a.rate for _, a, b in eligible) / total_minutes,
            sum((a.minutes + b.minutes) * b.rate for _, a, b in eligible) / total_minutes,
        )
        if rates[1] > 0:
            ratio = _round(rates[0] / rates[1])
            status = _interpret(ratio)
            # Freeze the original eligible strata and weights for leave-one-out rounds.
            plan = {
                'strata': [key for key, _, _ in eligible],
                'weights': [(a.minutes + b.minutes) / total_minutes for _, a, b in eligible],
            }
        else:
            status = '标准化对照率为零，率比未定义，请补充对照监测资料后复算'
    summary = _result_row(
        alarm, '直接标准化', '共同达标层', f'{len(eligible)} / {len(strata)}', exposed_total, comparison_total,
        rates, ratio, crude_ratio, status,
    )
    return summary, details, plan


def compute(rows: list[dict], options: dict) -> dict:
    if len(rows) < 2:
        raise ValueError('请导入至少两条机组日记录，并补齐同机房同负荷层的有无告警观察。')
    min_hours = _integer_option(options, 'min_hours', 24, 120_000, '每层每组最低监测小时')
    min_events = _integer_option(options, 'min_events', 3, 432_000_000, '每层两组最低目标事件总数')
    grouped = _group_exposure(rows)
    summaries = []
    details = []
    for alarm, strata in grouped.items():
        summary, alarm_details, _ = _analyze_alarm(alarm, strata, min_hours * 60, min_events)
        summaries.append(summary)
        details.extend(alarm_details)
    ranked = sorted(
        (row for row in summaries if row['率比'] is not None), key=lambda row: row['率比'], reverse=True,
    )
    if ranked and ranked[0]['率比'] > 1:
        top = ranked[0]
        headline = f"{top['伴随告警']}的标准化率比最高，为 {top['率比']:g}，建议优先联查。"
    elif ranked:
        headline = '达到门槛的伴随告警均未显示较高的标准化发生率。'
    else:
        headline = '目前没有可报告的标准化率比，请按分层明细补齐运行监测和目标事件资料。'

    return {
        'headline': headline,
        'metrics': {
            '监测机组': len({row['asset_id'] for row in rows}),
            '有效机组日': len(rows),
            '总监测小时': _round(sum(row['runtime_minutes'] for row in rows) / 60),
            '目标新发事件': sum(row['target_events'] for row in rows),
            '可报告标准化率比': len(ranked),
        },
        'rows': summaries + details,
        'notes': [
            '以机组日为观察窗口。用运行监测开始时已记录的伴随告警分组，只计本次监测中新发的蒸发器出水温度高事件。每项伴随告警分别比较，该告警缺席的记录进入对照组，即使同时记录了其他告警。',
            f'按机房和预先登记的计划负荷分层。每层有无告警组各须达到 {min_hours} 小时，两组须合计至少有 {min_events} 起目标新发事件。标准化至少需要两个共同达标层。',
            '层内发生率等于目标新发事件数除以监测小时乘 1000。粗率比先汇总达标层的两组事件和小时再相除。直接标准化对两组使用同一套权重，每层权重等于该层两组合计监测小时占全部达标层合计监测小时的比例。',
            '汇总行的事件数与小时是达标层的原始总量，汇总发生率是各层发生率的加权平均。各告警的达标层可能不同，复核时请先看明细和覆盖范围。',
            '率比为有告警组发生率除以无告警组发生率。大于 1 表示发生率较高，小于 1 表示较低，等于 1 表示展示精度内持平。对照发生率为零时，率比留空。',
            '这些结果供联查排序。机组可跨日重复出现，且可能同时出现多类伴随告警。这里的支持门槛用于筛选数据覆盖，关联强度仍可能受其他运行条件影响，无显著性或因果结论。',
        ],
        'chart': {
            'label': '达标伴随告警的标准化率比',
            'unit': '倍（1 为持平）',
            'points': [{'label': row['伴随告警'], 'value': row['率比']} for row in ranked],
        },
        'can_publish': bool(ranked),
    }


def plan_sensitivity(rows: list[dict], options: dict) -> dict:
    """Fix each alarm's original eligible strata and weights from the full dataset."""
    min_minutes = _integer_option(options, 'min_hours', 24, 120_000, '每层每组最低监测小时') * 60
    min_events = _integer_option(options, 'min_events', 3, 432_000_000, '每层两组最低目标事件总数')
    plans = {}
    ranked = []
    for alarm, strata in _group_exposure(rows).items():
        summary, _, plan = _analyze_alarm(alarm, strata, min_minutes, min_events)
        if plan is not None:
            plans[alarm] = plan
            ranked.append((alarm, summary['率比']))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return {
        'min_minutes': min_minutes,
        'min_events': min_events,
        'plans': plans,
        'baseline_top': ranked[0][0] if ranked else None,
    }


def leave_one_out(rows: list[dict], asset: str, bundle: dict) -> dict:
    """Recompute one round without the unit, on the original strata and weights only."""
    kept = [row for row in rows if row['asset_id'] != asset]
    outcome = {
        'asset_id': asset,
        'removed_days': len(rows) - len(kept),
        'removed_hours': _round(sum(row['runtime_minutes'] for row in rows if row['asset_id'] == asset) / 60),
        'top': None,
        'verdict': '缺数原因',
        'reason': '',
        'alarms': [],
    }
    if len(kept) < 2:
        outcome['reason'] = '剔除该机组后剩余记录不足两条，无法复算'
        outcome['alarms'] = [{'alarm': alarm, 'ratio': None, 'reason': '剔除后剩余记录不足两条'} for alarm in COALARMS]
        return outcome
    grouped = _group_exposure(kept)
    for alarm in COALARMS:
        plan = bundle['plans'].get(alarm)
        if plan is None:
            outcome['alarms'].append({'alarm': alarm, 'ratio': None, 'reason': '全量分析未产生标准化率比，不参与复算'})
            continue
        exposures = []
        reasons = []
        for (room, load), weight in zip(plan['strata'], plan['weights']):
            exposed, comparison = grouped[alarm].get((room, load), (Exposure(), Exposure()))
            reason = _support(exposed, comparison, bundle['min_minutes'], bundle['min_events'])
            if reason:
                reasons.append(f'{room} / {load}：{reason}')
            exposures.append((exposed, weight, comparison))
        if reasons:
            outcome['alarms'].append({'alarm': alarm, 'ratio': None, 'reason': '；'.join(reasons)})
            continue
        standardized = (
            sum(weight * exposed.rate for exposed, weight, _ in exposures),
            sum(weight * comparison.rate for _, weight, comparison in exposures),
        )
        if not standardized[1]:
            outcome['alarms'].append({'alarm': alarm, 'ratio': None, 'reason': '对照率归零，率比未定义'})
            continue
        outcome['alarms'].append({'alarm': alarm, 'ratio': _round(standardized[0] / standardized[1]), 'reason': ''})
    ranked = sorted((entry for entry in outcome['alarms'] if entry['ratio'] is not None),
                    key=lambda entry: entry['ratio'], reverse=True)
    if ranked:
        outcome['top'] = ranked[0]['alarm']
        outcome['verdict'] = '首位保持' if outcome['top'] == bundle['baseline_top'] else '首位易主'
    else:
        outcome['reason'] = '本轮所有告警均无法复算率比'
    return outcome


def sensitivity_summary(bundle: dict, assets: list[str], rounds: dict) -> dict:
    """Assemble the panel once every unit has a conclusion or a missing-data reason."""
    method = '逐台复核口径：逐台去掉该机组全部日期，沿用全量分析各告警原有的达标层与权重复算标准化率比；原层缺组、未达门槛或对照率归零时，该轮记原因，不换层凑排名。'
    if bundle['baseline_top'] is None:
        return {'applicable': False, 'method': method,
                'note': '全量分析没有可报告的标准化率比，无联查首位，逐台剔除复核不适用。'}
    ordered = [rounds[asset] for asset in assets]
    changed = [entry['asset_id'] for entry in ordered if entry['verdict'] == '首位易主']
    missing = [entry['asset_id'] for entry in ordered if entry['verdict'] == '缺数原因']
    held = len(ordered) - len(changed) - len(missing)
    if changed:
        headline = f"剔除{'、'.join(changed)}后联查首位易主，全量首位为{bundle['baseline_top']}，复核时请先核对这些机组的底账。"
    elif missing:
        headline = f'可复算的 {held} 台机组剔除后联查首位均保持为{bundle["baseline_top"]}。'
    else:
        headline = f'{len(ordered)} 台机组逐台剔除后联查首位均保持为{bundle["baseline_top"]}，首位结果稳健。'
    if missing:
        headline += f"{'、'.join(missing)}因缺数未得出本轮结论。"
    return {
        'applicable': True,
        'method': method,
        'baseline_top': bundle['baseline_top'],
        'total': len(ordered),
        'held': held,
        'changed': changed,
        'missing': missing,
        'rounds': ordered,
        'headline': headline,
    }
