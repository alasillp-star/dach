package com.oryx.impossiblereactor;

import android.app.Activity;
import android.content.Context;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.Random;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN);
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
        setContentView(new ReactorView(this));
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (Build.VERSION.SDK_INT < 30) {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    static class ReactorView extends View {
        private static final int MENU = 0;
        private static final int PLAYING = 1;
        private static final int CRASHED = 2;

        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Random rng = new Random();
        private final ArrayList<Particle> particles = new ArrayList<>();
        private final ArrayList<Floater> floaters = new ArrayList<>();
        private final ToneGenerator tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 42);
        private final Vibrator vibrator;

        private int state = MENU;
        private int w, h;
        private float cx, cy;
        private long lastNs;
        private float t;
        private float shake;
        private float flash;
        private float progress;
        private float stability = 100f;
        private int combo;
        private int taps;
        private int bestCombo;
        private int runNumber;
        private float pulsePhase;
        private float ringRotation;
        private float ringRotation2;
        private float sabotageAt;
        private float elapsed;
        private String crashReason = "";
        private String status = "SYNC READY";
        private float statusAlpha = 1f;
        private float menuPulse;
        private boolean soundOn = true;

        private final String[] sabotageReasons = {
                "PHASE SHIFT DETECTED",
                "CORE REJECTED",
                "TIME DESYNC",
                "SIGNAL SPOOFED",
                "QUANTUM LOCK FAILED",
                "OVERRIDE: ACCESS DENIED"
        };

        ReactorView(Context context) {
            super(context);
            setLayerType(View.LAYER_TYPE_SOFTWARE, null);
            vibrator = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
            p.setTypeface(android.graphics.Typeface.create("sans", android.graphics.Typeface.NORMAL));
            glow.setMaskFilter(new BlurMaskFilter(24f, BlurMaskFilter.Blur.NORMAL));
            setBackgroundColor(Color.rgb(3, 6, 18));
        }

        @Override
        protected void onSizeChanged(int width, int height, int oldw, int oldh) {
            w = width;
            h = height;
            cx = w / 2f;
            cy = h * 0.49f;
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            long now = System.nanoTime();
            float dt = lastNs == 0 ? 0.016f : Math.min(0.033f, (now - lastNs) / 1_000_000_000f);
            lastNs = now;
            update(dt);

            canvas.save();
            if (shake > 0.2f) {
                canvas.translate((rng.nextFloat() - .5f) * shake, (rng.nextFloat() - .5f) * shake);
            }

            drawBackground(canvas);
            if (state == MENU) drawMenu(canvas);
            else {
                drawHud(canvas);
                drawReactor(canvas);
                drawParticles(canvas);
                drawFloaters(canvas);
                if (state == CRASHED) drawCrashOverlay(canvas);
            }

            canvas.restore();
            if (flash > 0.01f) {
                p.setStyle(Paint.Style.FILL);
                p.setColor(Color.argb((int)(Math.min(1f, flash) * 190), 255, 70, 105));
                canvas.drawRect(0, 0, w, h, p);
            }

            postInvalidateOnAnimation();
        }

        private void update(float dt) {
            t += dt;
            menuPulse += dt;
            ringRotation += dt * (state == PLAYING ? 45f + taps * 0.35f : 14f);
            ringRotation2 -= dt * (state == PLAYING ? 68f + taps * 0.5f : 20f);
            pulsePhase += dt * (state == PLAYING ? 1.55f + taps * .018f : .7f);
            if (pulsePhase > 1f) pulsePhase -= 1f;
            shake *= (float)Math.pow(0.018, dt);
            flash *= (float)Math.pow(0.012, dt);
            statusAlpha = Math.max(0.35f, statusAlpha - dt * 0.55f);

            if (state == PLAYING) {
                elapsed += dt;
                stability -= dt * (1.05f + taps * .018f);
                if (stability <= 0f) crash("CORE DECAY");
            }

            Iterator<Particle> it = particles.iterator();
            while (it.hasNext()) {
                Particle q = it.next();
                q.life -= dt;
                if (q.life <= 0) it.remove();
                else {
                    q.x += q.vx * dt;
                    q.y += q.vy * dt;
                    q.vx *= Math.pow(.07, dt);
                    q.vy *= Math.pow(.07, dt);
                    q.vy += 35f * dt;
                }
            }

            Iterator<Floater> fit = floaters.iterator();
            while (fit.hasNext()) {
                Floater f = fit.next();
                f.life -= dt;
                f.y -= 42f * dt;
                if (f.life <= 0) fit.remove();
            }
        }

        private void drawBackground(Canvas c) {
            p.setStyle(Paint.Style.FILL);
            p.setShader(new LinearGradient(0, 0, 0, h,
                    Color.rgb(4, 8, 27), Color.rgb(2, 4, 13), Shader.TileMode.CLAMP));
            c.drawRect(0, 0, w, h, p);
            p.setShader(null);

            float drift = (t * 26f) % 70f;
            p.setStrokeWidth(1f);
            p.setColor(Color.argb(28, 74, 220, 255));
            for (float y = -70 + drift; y < h + 70; y += 70) c.drawLine(0, y, w, y, p);
            for (float x = 0; x < w; x += 70) c.drawLine(x, 0, x, h, p);

            p.setColor(Color.argb(18, 255, 255, 255));
            for (int i = 0; i < 22; i++) {
                float yy = (i * 97f + t * (7 + i % 4)) % h;
                float xx = (i * 173f) % w;
                c.drawCircle(xx, yy, 1.4f + (i % 3), p);
            }

            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2f);
            p.setColor(Color.argb(30, 70, 246, 255));
            float r = Math.min(w, h) * .53f;
            c.drawCircle(cx, cy, r, p);
        }

        private void drawMenu(Canvas c) {
            float pulse = 1f + .035f * (float)Math.sin(menuPulse * 3.2f);
            float logoR = Math.min(w, h) * .14f * pulse;

            glow.setStyle(Paint.Style.FILL);
            glow.setColor(Color.argb(90, 66, 240, 255));
            c.drawCircle(cx, h * .35f, logoR * 1.2f, glow);

            p.setShader(new RadialGradient(cx, h*.35f, logoR,
                    new int[]{Color.rgb(240,255,255), Color.rgb(44,225,255), Color.rgb(14,48,95)},
                    null, Shader.TileMode.CLAMP));
            p.setStyle(Paint.Style.FILL);
            c.drawCircle(cx, h * .35f, logoR, p);
            p.setShader(null);

            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(5f);
            p.setColor(Color.argb(210, 112, 246, 255));
            RectF rr = new RectF(cx-logoR*1.45f, h*.35f-logoR*1.45f, cx+logoR*1.45f, h*.35f+logoR*1.45f);
            c.drawArc(rr, ringRotation, 122, false, p);
            c.drawArc(rr, ringRotation+180, 72, false, p);

            drawText(c, "IMPOSSIBLE", cx, h*.56f, 20, Color.rgb(106,243,255), Paint.Align.CENTER, false);
            drawText(c, "REACTOR", cx, h*.615f, 45, Color.WHITE, Paint.Align.CENTER, true);
            drawText(c, "ثبّت النواة عند 100%", cx, h*.68f, 18, Color.rgb(187,201,220), Paint.Align.CENTER, false);

            float bw = w * .68f;
            float bh = 72f;
            float left = cx - bw/2f;
            float top = h*.77f;
            RectF button = new RectF(left, top, left+bw, top+bh);
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.argb(34, 93, 240, 255));
            c.drawRoundRect(button, 22, 22, p);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2.5f);
            p.setColor(Color.rgb(92, 238, 255));
            c.drawRoundRect(button, 22, 22, p);
            drawText(c, "ابدأ التجربة", cx, top+46, 20, Color.WHITE, Paint.Align.CENTER, true);
            drawText(c, "اضغط عندما تلتقي الحلقة بالمنطقة المضيئة", cx, h*.9f, 13, Color.rgb(116,137,168), Paint.Align.CENTER, false);
        }

        private void drawHud(Canvas c) {
            drawText(c, "IMPOSSIBLE REACTOR", 28, 44, 13, Color.rgb(104, 236, 255), Paint.Align.LEFT, true);
            drawText(c, String.format("RUN %02d", runNumber), w-28, 44, 13, Color.rgb(137,152,180), Paint.Align.RIGHT, true);

            float left = 28, top = 72, barW = w - 56, barH = 12;
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.rgb(20, 28, 49));
            c.drawRoundRect(new RectF(left, top, left+barW, top+barH), 8, 8, p);
            float prog = Math.max(0, Math.min(99.4f, progress));
            if (prog > 0) {
                p.setShader(new LinearGradient(left, 0, left+barW, 0,
                        Color.rgb(48, 227, 255), Color.rgb(179, 72, 255), Shader.TileMode.CLAMP));
                c.drawRoundRect(new RectF(left, top, left+barW*(prog/100f), top+barH), 8, 8, p);
                p.setShader(null);
            }
            drawText(c, String.format("STABILIZATION  %.1f%%", prog), left, top+35, 12, Color.rgb(190,205,230), Paint.Align.LEFT, true);

            int stabColor = stability > 55 ? Color.rgb(99, 244, 205) : (stability > 25 ? Color.rgb(255, 190, 75) : Color.rgb(255, 79, 102));
            drawText(c, String.format("CORE %03d", (int)Math.max(0, stability)), w-28, top+35, 12, stabColor, Paint.Align.RIGHT, true);

            drawText(c, "COMBO", 28, h-68, 11, Color.rgb(120,137,166), Paint.Align.LEFT, true);
            drawText(c, "x" + combo, 28, h-36, 28, Color.WHITE, Paint.Align.LEFT, true);
            drawText(c, status, w-28, h-42, 15, withAlpha(Color.rgb(108,238,255), statusAlpha), Paint.Align.RIGHT, true);
        }

        private void drawReactor(Canvas c) {
            float baseR = Math.min(w, h) * .132f;
            float targetR = baseR * 1.72f;
            float pulseR = baseR * (.73f + pulsePhase * 1.62f);

            // outer ambient glow
            glow.setColor(Color.argb(40, 76, 224, 255));
            glow.setStyle(Paint.Style.STROKE);
            glow.setStrokeWidth(22f);
            c.drawCircle(cx, cy, targetR, glow);

            // target sync band
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(18f);
            p.setColor(Color.argb(30, 94, 240, 255));
            c.drawCircle(cx, cy, targetR, p);
            p.setStrokeWidth(4f);
            p.setColor(Color.argb(210, 104, 246, 255));
            RectF tr = new RectF(cx-targetR, cy-targetR, cx+targetR, cy+targetR);
            c.drawArc(tr, ringRotation, 74, false, p);
            c.drawArc(tr, ringRotation+114, 42, false, p);
            c.drawArc(tr, ringRotation+238, 66, false, p);

            // mechanical ring 1
            float r2 = baseR * 2.18f;
            p.setStrokeWidth(3f);
            p.setColor(Color.argb(110, 104, 120, 164));
            RectF a = new RectF(cx-r2, cy-r2, cx+r2, cy+r2);
            for (int i=0;i<6;i++) c.drawArc(a, ringRotation2+i*60, 27, false, p);

            // mechanical ring 2 nodes
            float r3 = baseR * 2.55f;
            p.setColor(Color.argb(75, 86, 201, 255));
            p.setStrokeWidth(2f);
            c.drawCircle(cx, cy, r3, p);
            for (int i=0;i<8;i++) {
                double ang = Math.toRadians(ringRotation+i*45);
                float nx = cx + (float)Math.cos(ang)*r3;
                float ny = cy + (float)Math.sin(ang)*r3;
                p.setStyle(Paint.Style.FILL);
                p.setColor(Color.rgb(72, 213, 255));
                c.drawCircle(nx, ny, 4f, p);
            }

            // moving timing pulse
            glow.setStyle(Paint.Style.STROKE);
            glow.setStrokeWidth(13f);
            glow.setColor(Color.argb((int)(140*(1f-pulsePhase*.45f)), 197, 87, 255));
            c.drawCircle(cx, cy, pulseR, glow);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(4f);
            p.setColor(Color.rgb(224, 156, 255));
            c.drawCircle(cx, cy, pulseR, p);

            // core glow
            float breathing = 1f + .05f*(float)Math.sin(t*7.2f);
            glow.setStyle(Paint.Style.FILL);
            glow.setColor(Color.argb(125, 74, 230, 255));
            c.drawCircle(cx, cy, baseR*1.05f*breathing, glow);

            p.setShader(new RadialGradient(cx, cy, baseR,
                    new int[]{Color.WHITE, Color.rgb(82, 237, 255), Color.rgb(51, 104, 196), Color.rgb(20, 29, 72)},
                    new float[]{0f,.18f,.58f,1f}, Shader.TileMode.CLAMP));
            p.setStyle(Paint.Style.FILL);
            c.drawCircle(cx, cy, baseR*breathing, p);
            p.setShader(null);

            // core cut lines
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2f);
            p.setColor(Color.argb(150, 255,255,255));
            for (int i=0;i<4;i++) {
                float rr = baseR*(.42f+i*.15f);
                c.drawCircle(cx,cy,rr,p);
            }

            drawText(c, String.format("%.0f%%", Math.min(99f, progress)), cx, cy+8, 27, Color.rgb(3,16,34), Paint.Align.CENTER, true);
            drawText(c, "TAP ON SYNC", cx, cy + baseR*3.25f, 13, Color.rgb(146,164,195), Paint.Align.CENTER, true);
        }

        private void drawParticles(Canvas c) {
            p.setStyle(Paint.Style.FILL);
            for (Particle q : particles) {
                float a = Math.max(0, Math.min(1, q.life / q.maxLife));
                p.setColor(withAlpha(q.color, a));
                c.drawCircle(q.x, q.y, q.size * (.35f + a), p);
            }
        }

        private void drawFloaters(Canvas c) {
            for (Floater f : floaters) {
                float a = Math.max(0, Math.min(1, f.life / f.maxLife));
                drawText(c, f.text, f.x, f.y, f.size, withAlpha(f.color, a), Paint.Align.CENTER, true);
            }
        }

        private void drawCrashOverlay(Canvas c) {
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.argb(182, 3, 4, 14));
            c.drawRect(0,0,w,h,p);

            float cardW = w*.84f, cardH = 310f;
            RectF card = new RectF(cx-cardW/2f, cy-cardH/2f, cx+cardW/2f, cy+cardH/2f);
            p.setColor(Color.argb(245, 12, 18, 36));
            c.drawRoundRect(card, 30,30,p);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2f);
            p.setColor(Color.rgb(255,72,102));
            c.drawRoundRect(card,30,30,p);

            drawText(c, "REACTOR LOST", cx, card.top+62, 16, Color.rgb(255,88,113), Paint.Align.CENTER, true);
            drawText(c, crashReason, cx, card.top+112, 22, Color.WHITE, Paint.Align.CENTER, true);
            drawText(c, String.format("وصلت إلى %.1f%%", Math.min(99.4f, progress)), cx, card.top+162, 17, Color.rgb(182,197,222), Paint.Align.CENTER, false);
            drawText(c, "BEST COMBO  x"+bestCombo, cx, card.top+204, 13, Color.rgb(108,236,255), Paint.Align.CENTER, true);

            RectF retry = new RectF(card.left+38, card.bottom-70, card.right-38, card.bottom-20);
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.rgb(28, 182, 218));
            c.drawRoundRect(retry, 16,16,p);
            drawText(c, "إعادة المحاولة", cx, retry.centerY()+7, 17, Color.rgb(5,13,25), Paint.Align.CENTER, true);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (e.getAction() != MotionEvent.ACTION_DOWN) return true;
            float x = e.getX(), y = e.getY();
            if (state == MENU) {
                startRun();
                return true;
            }
            if (state == CRASHED) {
                startRun();
                return true;
            }
            handleTap(x,y);
            return true;
        }

        private void startRun() {
            state = PLAYING;
            runNumber++;
            progress = 0;
            stability = 100;
            combo = 0;
            taps = 0;
            elapsed = 0;
            pulsePhase = .1f + rng.nextFloat()*.3f;
            sabotageAt = 88.5f + rng.nextFloat()*9.2f;
            crashReason = "";
            status = "SYNC READY";
            statusAlpha = 1f;
            particles.clear();
            floaters.clear();
            burst(cx, cy, 42, Color.rgb(82,232,255), 260f);
            beep(ToneGenerator.TONE_PROP_ACK, 90);
            haptic(18);
        }

        private void handleTap(float x, float y) {
            taps++;
            float baseR = Math.min(w,h)*.132f;
            float targetR = baseR*1.72f;
            float pulseR = baseR*(.73f+pulsePhase*1.62f);
            float error = Math.abs(pulseR-targetR);
            float perfectBand = baseR*.18f;
            float goodBand = baseR*.42f;

            if (error <= perfectBand) {
                combo++;
                bestCombo = Math.max(bestCombo, combo);
                float gain = 8.6f + Math.min(5.8f, combo*.38f);
                progress += gain;
                stability = Math.min(100, stability+3.4f);
                status = combo >= 4 ? "PERFECT CHAIN x"+combo : "PERFECT SYNC";
                statusAlpha = 1f;
                floaters.add(new Floater("PERFECT +"+(int)gain, cx, cy-40, 18, Color.rgb(111,255,218)));
                burst(cx,cy,34,Color.rgb(100,255,220),310f);
                ringBurst(targetR, Color.rgb(100,255,220));
                beep(ToneGenerator.TONE_PROP_BEEP2, 55);
                haptic(24);
            } else if (error <= goodBand) {
                combo++;
                bestCombo = Math.max(bestCombo,combo);
                float gain = 4.4f + Math.min(2.5f, combo*.18f);
                progress += gain;
                status = "SYNC +"+(int)gain;
                statusAlpha = 1f;
                floaters.add(new Floater("GOOD +"+(int)gain,cx,cy-35,16,Color.rgb(106,222,255)));
                burst(cx,cy,20,Color.rgb(83,215,255),230f);
                beep(ToneGenerator.TONE_PROP_BEEP,45);
                haptic(13);
            } else {
                combo=0;
                stability-=13.5f;
                progress=Math.max(0,progress-2.3f);
                status="DESYNC";
                statusAlpha=1f;
                shake=Math.max(shake,12f);
                flash=.15f;
                floaters.add(new Floater("DESYNC -2",x,y,16,Color.rgb(255,98,122)));
                burst(x,y,18,Color.rgb(255,78,111),180f);
                beep(ToneGenerator.TONE_PROP_NACK,80);
                haptic(42);
            }

            // The design intentionally has no win state. Every run is sabotaged before 100%.
            if (progress >= sabotageAt) {
                progress = Math.min(99.4f, Math.max(progress, 96.2f + rng.nextFloat()*3.1f));
                crash(sabotageReasons[rng.nextInt(sabotageReasons.length)]);
            } else if (stability <= 0) {
                crash("CORE COLLAPSE");
            }
        }

        private void crash(String reason) {
            if (state != PLAYING) return;
            state = CRASHED;
            crashReason = reason;
            combo=0;
            shake=38f;
            flash=1f;
            burst(cx,cy,120,Color.rgb(255,67,103),620f);
            burst(cx,cy,70,Color.rgb(137,74,255),440f);
            beep(ToneGenerator.TONE_CDMA_ABBR_ALERT, 240);
            haptic(130);
        }

        private void ringBurst(float radius, int color) {
            for (int i=0;i<18;i++) {
                double a = Math.PI*2*i/18.0 + rng.nextFloat()*.1;
                float x = cx+(float)Math.cos(a)*radius;
                float y = cy+(float)Math.sin(a)*radius;
                float speed = 80+rng.nextFloat()*120;
                particles.add(new Particle(x,y,(float)Math.cos(a)*speed,(float)Math.sin(a)*speed,3+rng.nextFloat()*3,.45f,color));
            }
        }

        private void burst(float x, float y, int count, int color, float speed) {
            for (int i=0;i<count;i++) {
                double a = rng.nextFloat()*Math.PI*2;
                float s = speed*(.18f+rng.nextFloat()*.82f);
                particles.add(new Particle(x,y,(float)Math.cos(a)*s,(float)Math.sin(a)*s,2+rng.nextFloat()*5,.35f+rng.nextFloat()*.7f,color));
            }
        }

        private void beep(int toneId, int ms) {
            if (!soundOn) return;
            try { tone.startTone(toneId, ms); } catch (Exception ignored) {}
        }

        private void haptic(long ms) {
            if (vibrator == null || !vibrator.hasVibrator()) return;
            try {
                if (Build.VERSION.SDK_INT >= 26) vibrator.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
                else vibrator.vibrate(ms);
            } catch (Exception ignored) {}
        }

        private void drawText(Canvas c, String s, float x, float y, float sp, int color, Paint.Align align, boolean bold) {
            p.setShader(null);
            p.setStyle(Paint.Style.FILL);
            p.setTextAlign(align);
            p.setTextSize(sp * getResources().getDisplayMetrics().scaledDensity);
            p.setColor(color);
            p.setTypeface(android.graphics.Typeface.create("sans", bold ? android.graphics.Typeface.BOLD : android.graphics.Typeface.NORMAL));
            c.drawText(s, x, y, p);
        }

        private int withAlpha(int color, float a) {
            return Color.argb((int)(255*Math.max(0,Math.min(1,a))), Color.red(color), Color.green(color), Color.blue(color));
        }

        static class Particle {
            float x,y,vx,vy,size,life,maxLife; int color;
            Particle(float x,float y,float vx,float vy,float size,float life,int color){
                this.x=x;this.y=y;this.vx=vx;this.vy=vy;this.size=size;this.life=life;this.maxLife=life;this.color=color;
            }
        }
        static class Floater {
            String text; float x,y,size,life,maxLife; int color;
            Floater(String text,float x,float y,float size,int color){
                this.text=text;this.x=x;this.y=y;this.size=size;this.life=.8f;this.maxLife=.8f;this.color=color;
            }
        }
    }
}
