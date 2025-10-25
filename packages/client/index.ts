import createClient from "openapi-fetch";
import type { paths } from "@procuresight/types";

export const api = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
});