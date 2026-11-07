import { useState } from 'react';
import { CheckCircle2, MessageCircle, QrCode } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/store/useAuthStore';

export default function Pricing() {
  const [showQR, setShowQR] = useState(false);
  const [verificationPending, setVerificationPending] = useState(false);
  const userEmail = useAuthStore((state) => state.user?.email ?? '');
  const whatsappMessage = encodeURIComponent(
    `Hi! I just paid for SyncCut Pro. My account email is ${userEmail}.`,
  );

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0c] px-4 text-[#ededed]">
      <section className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#121217] p-8 text-center shadow-2xl">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#00E5FF]">SyncCut Studio</p>
        <h1 className="mt-3 text-3xl font-bold text-white">Choose your plan</h1>
        <p className="mt-3 text-sm text-[#a1a1aa]">
          Unlock AI cuts, longer projects, and up to 4K exports with Pro.
        </p>
        <div className="mt-8 rounded-xl border border-[#00E5FF]/30 bg-[#00E5FF]/5 p-6">
          <h2 className="text-xl font-semibold text-white">Pro</h2>
          <p className="mt-2 text-3xl font-bold text-[#00E5FF]">₹1,500<span className="text-sm font-medium text-[#a1a1aa]"> / month</span></p>
          <Button
            onClick={() => setShowQR(true)}
            className="mt-6 w-full bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff]"
          >
            <QrCode className="mr-2 h-4 w-4" />
            Upgrade to Pro
          </Button>
        </div>
      </section>

      <Dialog open={showQR} onOpenChange={setShowQR}>
        <DialogContent className="border-border bg-panel text-center text-text sm:max-w-md">
          {verificationPending ? (
            <div className="py-4">
              <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-400" />
              <DialogTitle className="mt-4 text-xl">Verification Pending</DialogTitle>
              <DialogDescription className="mt-2 text-sm leading-relaxed">
                Thanks for upgrading! An admin will verify your payment and upgrade your account within 1 hour.
                We’ll send a confirmation email to <strong className="text-text">{userEmail}</strong>.
              </DialogDescription>
              <Button
                onClick={() => setShowQR(false)}
                className="mt-6 w-full bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff]"
              >
                Done
              </Button>
            </div>
          ) : (
            <>
              <DialogTitle>Complete Your Upgrade</DialogTitle>
              <DialogDescription>
                Scan the GPay QR code to pay, then send your payment screenshot on WhatsApp.
              </DialogDescription>

              <div className="my-4 flex justify-center rounded-xl bg-white p-4">
                <img src="" alt="GPay QR" className="h-64 w-64 object-contain" />
              </div>

              <p className="mb-4 text-sm text-muted">
                Account to activate: <strong>{userEmail}</strong>
              </p>

              <a
                href={`https://wa.me/8261968994?text=${whatsappMessage}`}
                target="_blank"
                rel="noreferrer"
                onClick={() => setVerificationPending(true)}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-emerald-500 py-3 font-bold text-white hover:bg-emerald-600"
              >
                <MessageCircle size={18} /> I have paid on WhatsApp
              </a>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
