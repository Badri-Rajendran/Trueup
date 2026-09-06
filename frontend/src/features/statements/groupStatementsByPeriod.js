/**
 * `GET /statements` returns every snapshot ever published, including every watermark a period was
 * republished under (backend/app/models/restatement/published_snapshot.py), sorted period_start
 * desc then publish_watermark desc. Grouping by `period_start` here turns that into one row per
 * period, with `current` (newest watermark) and `original` (oldest) split out for design-system
 * §8.1's restated-figure treatment.
 */
export function groupStatementsByPeriod(statements) {
  const byPeriod = new Map()
  for (const statement of statements) {
    const key = statement.period_start
    if (!byPeriod.has(key)) {
      byPeriod.set(key, [])
    }
    byPeriod.get(key).push(statement)
  }

  return Array.from(byPeriod.values()).map((versions) => ({
    periodStart: versions[0].period_start,
    periodEnd: versions[0].period_end,
    current: versions[0],
    original: versions[versions.length - 1],
    isRestated: versions.length > 1,
  }))
}
