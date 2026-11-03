/**
 * E2E Test Configuration for URLs and Endpoints
 * 
 * Centralizes all URL configuration for E2E tests.
 * Uses environment variables with sensible defaults.
 */

export const config = {
  /**
   * Base URL for the API server
   * Override with API_BASE_URL environment variable
   */
  baseUrl: process.env.API_BASE_URL || 'http://localhost:5000',
  
  /**
   * Test database connection URLs
   * Override with environment variables for local/CI testing
   */
  testDatabases: {
    postgres: process.env.TEST_POSTGRES_URL || 'postgresql://postgres:postgres@localhost:5432/testdb',
    mysql: process.env.TEST_MYSQL_URL || 'mysql://root:password@localhost:3306/testdb',
  },
} as const;

/**
 * Get the base URL for API calls
 */
export function getBaseUrl(): string {
  return config.baseUrl;
}

/**
 * Get test database connection URLs
 */
export function getTestDatabases() {
  return config.testDatabases;
}
