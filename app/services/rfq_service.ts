export type RFQItem = {
  name: string;
  quantity?: number;
  unit?:
    | "units"
    | "sets"
    | "pieces"
    | "kg"
    | "g"
    | "tonnes"
    | "liters"
    | "ml"
    | "barrels"
    | "meters"
    | "cm"
    | "mm"
    | "feet"
    | "inches"
    | "packs"
    | "boxes"
    | "rolls"
    | "cans"
    | "bottles";
  essential?: boolean;
  size_spec?: string;
  note?: string;
  // legacy support
  qty?: string;
};

export type RFQ = {
  id: number;
  user_id?: number; // optional on the client; server owns it
  title: string;
  buyer_company: string;
  port: string;
  deadline_days: number;
  budget_min?: number;
  budget_max?: number;
  tags?: string[];
  required_items: RFQItem[];
  terms?: { delivery?: string; payment?: string };
  created_at: string; // ISO string from backend
};

export type RFQCreatePayload = Omit<RFQ, "id" | "created_at" | "user_id">;

export const rfqService = {
  async list(): Promise<RFQ[]> {
    const { data } = await AxiosX.get("/api/v1/rfqs");
    return data;
  },

  async create(payload: RFQCreatePayload): Promise<RFQ> {
    const { data } = await AxiosX.post("/api/v1/rfqs", payload);
    return data;
  },

  async get(id: string | number): Promise<RFQ> {
    const { data } = await AxiosX.get(`/api/v1/rfqs/${id}`);
    return data;
  },

  pdfUrl(id: string | number) {
    return `${AxiosX.defaults.baseURL}/api/v1/rfqs/${id}/pdf`;
  },
};
