// The one Playwright smoke of the migration (ticket #50, M7 exit; draft
// preview phase per #35): a REAL streamed chat turn through the served
// SPA. No mocks — the turn goes through the model router and the live
// tool backends.
//
// Flow: open `/` -> send a message -> assert tokens stream live and a
// tool-call chip reaches complete -> the draft PREVIEW card renders
// inline -> ✎ Edit -> the form -> save -> confirmed card -> the search
// is in /bargains.

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

  // 3. The draft renders inline as a read-only PREVIEW card (#35):
  //    five labeled rows and the three actions.
  const card = page.locator(".dr-card").first();
  await expect(card).toBeVisible({ timeout: 120_000 });
  await expect(card.locator(".dr-row")).toHaveCount(5);
  await expect(card.getByRole("button", { name: "Save as-is" })).toBeVisible();

  // 4. ✎ Edit reveals the SearchForm; edit the location to prove
  //    editability end-to-end.
  await card.getByRole("button", { name: /Edit/ }).click();
  await expect(card.getByLabel("Location")).toBeVisible();
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
