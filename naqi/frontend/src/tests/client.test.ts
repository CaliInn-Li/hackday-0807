import { describe, expect, it } from "vitest";
import { ApiClient, ApiError, type TokenStore } from "../api/client";

function store(initial: string | null = null): TokenStore {
  let value = initial;
  return {
    get: () => value,
    set: (next) => { value = next; },
    clear: () => { value = null; },
  };
}

describe("ApiClient", () => {
  it("adds bearer auth and normalizes list responses", async () => {
    const requests: Array<{ url: string; headers: Headers; body?: BodyInit | null }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      requests.push({ url: String(input), headers: new Headers(init?.headers), body: init?.body });
      return new Response(JSON.stringify({ items: [{ id: "c-1", name: "角色", status: "ready" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    const client = new ApiClient({ baseUrl: "http://api.test/", tokenStore: store("secret-value"), fetchImpl });
    const characters = await client.listCharacters();
    expect(characters[0]?.id).toBe("c-1");
    expect(requests[0]?.url).toBe("http://api.test/v1/assets/characters");
    expect(requests[0]?.headers.get("Authorization")).toBe("Bearer secret-value");
  });

  it("uses multipart for uploads without overwriting browser content type", async () => {
    let request: { headers: Headers; body?: BodyInit | null } | undefined;
    const fetchImpl: typeof fetch = async (_input, init) => {
      request = { headers: new Headers(init?.headers), body: init?.body };
      return new Response(JSON.stringify({ id: "m-1" }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = new ApiClient({ tokenStore: store(), fetchImpl });
    await client.uploadMotion(new File(["video"], "clip.mp4", { type: "video/mp4" }), { cameraMode: "static" });
    expect(request?.headers.has("Content-Type")).toBe(false);
    expect(request?.body).toBeInstanceOf(FormData);
    expect((request?.body as FormData).get("camera_mode")).toBe("static");
  });

  it("redacts sensitive values from API errors", async () => {
    const fetchImpl: typeof fetch = async () => new Response(JSON.stringify({ detail: "Bearer secret-value rejected" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
    const client = new ApiClient({ tokenStore: store("secret-value"), fetchImpl });
    await expect(client.listJobs()).rejects.toMatchObject({ status: 401 });
    try {
      await client.listJobs();
    } catch (error: unknown) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as Error).message).not.toContain("secret-value");
    }
  });
});
