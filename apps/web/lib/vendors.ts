import { api } from "../../../packages/client";

export async function getVendors() {
  const { data, error } = await api.GET("/vendors");
  if (error) throw error;
  return data; // typed as Vendor[]
}