// Item 29: loads the Razorpay Checkout script tag at runtime, once.
// The Window.Razorpay declaration lives here rather than a separate
// razorpay.d.ts: a same-named .d.ts is shadowed by this .ts file and never
// gets included in the program.
declare global {
  interface Window {
    // Razorpay Checkout ships no official types; an untyped any is
    // the only accurate description of this third-party script global.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Razorpay: any;
  }
}

const RAZORPAY_SCRIPT_URL = "https://checkout.razorpay.com/v1/checkout.js";

let loadPromise: Promise<void> | null = null;

export function loadRazorpayCheckout(): Promise<void> {
  if (typeof window === "undefined") return Promise.reject(new Error("No window"));
  if (window.Razorpay) return Promise.resolve();
  if (loadPromise) return loadPromise;

  loadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_SCRIPT_URL;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay Checkout."));
    document.body.appendChild(script);
  });
  return loadPromise;
}
