// Wire types for BoldTrader API v1 — snake_case straight from the contract
// (docs/api-contract.md); no case conversion layer.

export interface Search {
  id: number;
  summary: string;
  product_identity: string;
  target_price: number | null;
  location: string | null;
  queries: string[];
  exclusions: string[];
  version: number;
  status: string;
  match_count: number;
  created_at: string;
  updated_at: string;
}

export interface SearchListItem {
  id: number;
  summary: string;
  status: string;
  match_count: number;
  updated_at: string;
}

export interface Draft {
  summary: string;
  product_identity: string;
  queries: string[];
  exclusions: string[];
  target_price: number | null;
  location: string | null;
}

export interface Enrichment {
  status: string;
  product: unknown;
  condition: string | null;
  bundle: unknown;
  confidence: number | null;
}

export interface ResultCard {
  listing_id: string;
  title: string;
  url: string;
  asking_price: number | null;
  marketplace: string;
  image_url: string | null;
  verdict: string;
  availability: string;
  authored_description: string | null;
  enrichment: Enrichment | null;
}

export interface ListingCard {
  id: string;
  title: string;
  url: string;
  asking_price: number | null;
  marketplace: string;
  image_url: string | null;
}

export interface Envelope<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface MarketplaceSearchResult extends Envelope<ListingCard> {
  failed_marketplaces: string[];
}

export interface ChatSessionSummary {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  role: string;
  content: string;
  created_at: string;
}

export interface ChatSession {
  id: number;
  title: string;
  messages: ChatMessage[];
}

export interface Liveness {
  done: boolean;
  banner: string | null;
  dead: string[];
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}
