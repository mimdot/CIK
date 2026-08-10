import "@testing-library/jest-dom";

// jsdom provides localStorage in the window scope; ensure a fresh store per test.
beforeEach(() => {
  window.localStorage.clear();
});
