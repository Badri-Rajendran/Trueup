// Shared "home" route for router fallback and RequireRole: customers onboard, staff go to breaks queue.
export function defaultRouteForPrincipal(principal) {
  return principal?.role === 'customer' ? '/dashboard' : '/admin/breaks'
}
