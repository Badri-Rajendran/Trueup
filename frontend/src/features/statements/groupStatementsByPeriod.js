/** Groups snapshots by period into current (newest) / original (oldest), per design-system §8.1. */
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
