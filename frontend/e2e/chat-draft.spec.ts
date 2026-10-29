// The one Playwright smoke of the migration (ticket #50, M7 exit):
// a REAL streamed chat turn through the served SPA. No mocks — the turn
// goes through the model router and the live tool backends.
//
// Flow: open `/` -> send a message -> assert tokens stream live and a
// tool-call chip reaches complete -> the draft card renders inline ->
// edit a field -> save -> confirmed card -> the search is in /bargains.

import { test, expect, type Page } from "@playwright/test";

async function send(page: Page, text: string) {
  await page.getByLabel("Chat message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("streamed chat turn: live tokens, completed tool chip, draft saves to /bargains", async ({
  page,
}) => {
  await page.goto("/");

  await send(
    page,
    `I want a used HP Z440 workstation under $300 in Kenmore, WA. ` +
      `First use the search_listings tool to look up "HP Z440" and see ` +
      `what we've already seen, then create a Bargain Search for it with ` +
      `a short reply including the draft. ` +
      `Summary: "HP Z440 workstation under $300".`,
  );
  const streamText = page.locator(".ct-caret").first();
  await expect(streamText).toBeVisible();
  await expect
    .poll(async () => (await streamText.textContent())?.length ?? 0, {
      message: "expected streamed tokens to grow the live text",
    })
    .toBeGreaterThan(20);

  // 2. A tool-call chip reaches complete (✓, not the running spinner).
  //    Tool rounds end before the final prose, so wait on the turn, not a
  //    fixed frame count.
  await expect(page.locator(".ct-chip-done").first()).toBeVisible({
    timeout: 120_000,
  });

  // 3. The draft renders inline as a pre-filled SearchForm card.
  const card = page.locator(".dr-card").first();
  await expect(card).toBeVisible({ timeout: 120_000 });
  await expect(card.getByLabel("Summary")).toHaveValue(/.+/);
  await expect(card.getByLabel("Product identity")).toHaveValue(/.+/);
  // The queries control is the TagInput inside the card; its accessible
  // name comes from the placeholder (the wrapping label holds chips).
  await expect(card.getByPlaceholder("type a query, press Enter")).toBeVisible();

  // 4. The card stays usable while the turn finishes; then save with an
  //    edited location to prove editability end-to-end.
  await card.getByLabel("Location").fill("Kenmore, WA");
  await card.getByRole("button", { name: "Save as Bargain Search" }).click();

  // 5. Confirmed state with a link to the new search.
  const saved = page.locator(".dr-saved");
  await expect(saved).toBeVisible();
  const savedSummary = (await saved.locator("a").textContent())!;
  const searchHref = (await saved.locator("a").getAttribute("href"))!;
  expect(searchHref).toMatch(/^\/bargains\/\d+$/);

  // 6. The new search is in /bargains without a manual reload path —
  //    we navigate fresh; the create invalidation already refetched.
  await page.goto("/bargains");
  await expect(
    page.getByRole("link", { name: savedSummary, exact: true }).first(),
  ).toBeVisible();
});
