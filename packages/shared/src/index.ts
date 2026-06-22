/**
 * @geo/shared — cross-service contracts.
 *
 * This package is the TypeScript-side mirror of contracts that both the
 * Fastify API and the Python pipeline must agree on. The DB schema (in /db)
 * remains the primary contract; this covers the HTTP boundary between services.
 *
 * Keep these in lockstep with the JSON Schemas in ./schemas, which the Python
 * service validates against.
 */

export * from "./health.js";
export * from "./internal.js";
