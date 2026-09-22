/**
 * Test setup for the client.
 *
 * `@testing-library/jest-dom` adds the DOM matchers (`toBeDisabled`, `toHaveTextContent`, ...); the cleanup
 * keeps one test's rendered tree out of the next one's queries.
 */
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
