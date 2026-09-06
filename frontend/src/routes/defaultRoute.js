// Shared by the router shell (unmatched paths) and `RequireRole` (a role mismatch) so both land an
// authenticated principal on the same "home" screen for their role — customers onboard first,
// staff have no onboarding step and land on the breaks queue.
export function defaultRouteForPrincipal(principal) {
  return principal?.role === 'customer' ? '/onboarding' : '/admin/breaks'
}
