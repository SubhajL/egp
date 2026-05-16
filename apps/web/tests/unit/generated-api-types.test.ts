import { describe, expect, it } from "vitest";

import openapiSchema from "../../src/lib/generated/openapi.json";
import type { paths } from "../../src/lib/generated/api-types";

type ProjectListResponse =
  paths["/v1/projects"]["get"]["responses"][200]["content"]["application/json"];

describe("generated API contract", () => {
  it("commits the backend OpenAPI schema used for type generation", () => {
    expect(openapiSchema.openapi).toBe("3.1.0");
    expect(openapiSchema.info.title).toBe("e-GP Intelligence Platform");
    expect(openapiSchema.paths).toHaveProperty("/v1/projects");
  });

  it("exposes generated response types for frontend callers", () => {
    const response: ProjectListResponse = {
      projects: [],
      total: 0,
      limit: 50,
      offset: 0,
    };

    expect(response.projects).toEqual([]);
    expect(response.limit).toBe(50);
  });
});
