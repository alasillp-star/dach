package com.oryx.impossiblereactor;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.Random;

public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try { requestWindowFeature(Window.FEATURE_NO_TITLE); } catch (Throwable ignored) {}
        try { getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN); } catch (Throwable ignored) {}
        safeImmersive();
        setContentView(new ReactorView(this));
    }

    @Override
    protected void onResume() {
        super.onResume();
        safeImmersive();
    }

    private void safeImmersive() {
        try {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            );
        } catch (Throwable ignored) {}
    }

    public static final class ReactorView extends View {
        private static final int MENU = 0;
        private static final int PLAY = 1;
        private static final int DEAD = 2;

        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Random rng = new Random();
        private final ArrayList<Particle> particles = new ArrayList<>();
        private final ArrayList<FloatingText> texts = new ArrayList<>();
        private final Vibrator vibrator;

        private int state = MENU;
        private int w, h;
        private float cx, cy;
        private long lastNs;
        private float time;
        private float ringA;
        private float ringB;
        private float pulse;
        private float progress;
        private float energy = 100f;
        private int combo;
        private int bestCombo;
        private int run;
        private float flash;
        private float shake;
        private float targetFail;
        private String status = "READY";
        private String failReason = "";

        private final String[] failures = {
                "PHASE COLLAPSE",
                "CORE REJECTED",
                "TIME DESYNC",
                "SIGNAL CORRUPTED",
                "LOCK FAILED",
                "ACCESS DENIED"
        };

        ReactorView(Context context) {
            super(context);
            setBackgroundColor(Color.rgb(3, 6, 18));
            setFocusable(true);
            setClickable(true);
            Vibrator vib = null;
            try { vib = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE); } catch (Throwable ignored) {}
            vibrator = vib;
        }

        @Override
        protected void onSizeChanged(int width, int height, int oldw, int oldh) {
            w = Math.max(1, width);
            h = Math.max(1, height);
            cx = w * 0.5f;
            cy = h * 0.50f;
        }

        @Override
        protected void onDraw(Canvas c) {
            long now = System.nanoTime();
            float dt = lastNs == 0 ? 0.016f : Math.min(0.033f, Math.max(0.001f, (now - lastNs) / 1_000_000_000f));
            lastNs = now;
            update(dt);

            c.save();
            if (shake > 0.2f) {
                c.translate((rng.nextFloat() - .5f) * shake, (rng.nextFloat() - .5f) * shake);
            }
            drawBackground(c);
            if (state == MENU) drawMenu(c);
            else {
                drawHud(c);
                drawReactor(c);
                drawParticles(c);
                drawTexts(c);
                if (state == DEAD) drawDead(c);
            }
            c.restore();

            if (flash > 0.01f) {
                p.setShader(null);
                p.setStyle(Paint.Style.FILL);
                p.setColor(Color.argb((int)(Math.min(1f, flash) * 170), 255, 50, 90));
                c.drawRect(0, 0, w, h, p);
            }

            postInvalidateOnAnimation();
        }

        private void update(float dt) {
            time += dt;
            ringA = (ringA + dt * (state == PLAY ? 62f + combo * 2.2f : 18f)) % 360f;
            ringB = (ringB - dt * (state == PLAY ? 94f + combo * 2.8f : 27f)) % 360f;
            pulse += dt * (state == PLAY ? 1.32f + combo * .025f : .55f);
            if (pulse > 1f) pulse -= 1f;
            flash *= (float)Math.pow(0.02, dt);
            shake *= (float)Math.pow(0.025, dt);

            if (state == PLAY) {
                energy -= dt * (1.25f + combo * .025f);
                if (energy <= 0f) fail("CORE DECAY");
            }

            Iterator<Particle> it = particles.iterator();
            while (it.hasNext()) {
                Particle q = it.next();
                q.life -= dt;
                if (q.life <= 0) { it.remove(); continue; }
                q.x += q.vx * dt;
                q.y += q.vy * dt;
                q.vx *= 0.985f;
                q.vy *= 0.985f;
            }

            Iterator<FloatingText> ft = texts.iterator();
            while (ft.hasNext()) {
                FloatingText f = ft.next();
                f.life -= dt;
                f.y -= 55f * dt;
                if (f.life <= 0) ft.remove();
            }
        }

        private void drawBackground(Canvas c) {
            p.setStyle(Paint.Style.FILL);
            p.setShader(new LinearGradient(0, 0, 0, h,
                    Color.rgb(6, 10, 35), Color.rgb(1, 3, 12), Shader.TileMode.CLAMP));
            c.drawRect(0, 0, w, h, p);
            p.setShader(null);

            p.setStrokeWidth(1f);
            p.setColor(Color.argb(28, 61, 214, 255));
            float grid = Math.max(54f, Math.min(w, h) / 8f);
            float drift = (time * 18f) % grid;
            for (float y = -grid + drift; y < h + grid; y += grid) c.drawLine(0, y, w, y, p);
            for (float x = 0; x < w; x += grid) c.drawLine(x, 0, x, h, p);

            for (int i = 0; i < 24; i++) {
                float sx = (i * 173f) % w;
                float sy = (i * 101f + time * (8f + i % 5)) % h;
                p.setStyle(Paint.Style.FILL);
                p.setColor(Color.argb(25 + (i % 4) * 8, 160, 235, 255));
                c.drawCircle(sx, sy, 1.2f + (i % 3), p);
            }
        }

        private void drawMenu(Canvas c) {
            float base = Math.min(w, h) * .13f;
            float r = base * (1f + .04f * (float)Math.sin(time * 3f));

            p.setStyle(Paint.Style.FILL);
            p.setShader(new RadialGradient(cx, h * .34f, r * 1.8f,
                    new int[]{Color.argb(145, 72, 245, 255), Color.argb(45, 70, 100, 255), Color.TRANSPARENT},
                    null, Shader.TileMode.CLAMP));
            c.drawCircle(cx, h * .34f, r * 1.8f, p);
            p.setShader(null);

            p.setShader(new RadialGradient(cx, h * .34f, r,
                    new int[]{Color.WHITE, Color.rgb(85, 245, 255), Color.rgb(30, 75, 160)},
                    null, Shader.TileMode.CLAMP));
            c.drawCircle(cx, h * .34f, r, p);
            p.setShader(null);

            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(5f);
            p.setColor(Color.rgb(110, 240, 255));
            RectF rr = new RectF(cx-r*1.45f, h*.34f-r*1.45f, cx+r*1.45f, h*.34f+r*1.45f);
            c.drawArc(rr, ringA, 120, false, p);
            c.drawArc(rr, ringA+180, 65, false, p);

            text(c, "IMPOSSIBLE", cx, h*.55f, 18, Color.rgb(101, 238, 255), Paint.Align.CENTER, true);
            text(c, "REACTOR", cx, h*.61f, 42, Color.WHITE, Paint.Align.CENTER, true);
            text(c, "ثبت النواة عند 100%", cx, h*.67f, 17, Color.rgb(187, 202, 226), Paint.Align.CENTER, false);

            float bw = w*.70f, bh = Math.max(62f, h*.065f);
            RectF b = new RectF(cx-bw/2f, h*.76f, cx+bw/2f, h*.76f+bh);
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.argb(60, 60, 220, 255));
            c.drawRoundRect(b, 24, 24, p);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2.5f);
            p.setColor(Color.rgb(90, 238, 255));
            c.drawRoundRect(b, 24, 24, p);
            text(c, "ابدأ التجربة", cx, b.centerY()+7, 19, Color.WHITE, Paint.Align.CENTER, true);
            text(c, "اضغط عندما تلتقي النبضة مع الحلقة", cx, h*.90f, 13, Color.rgb(117, 139, 171), Paint.Align.CENTER, false);
        }

        private void drawHud(Canvas c) {
            text(c, "IMPOSSIBLE REACTOR", 26, 42, 12, Color.rgb(100, 235, 255), Paint.Align.LEFT, true);
            text(c, "RUN " + run, w-26, 42, 12, Color.rgb(140, 153, 180), Paint.Align.RIGHT, true);

            float l = 26, top = 70, bw = w-52, bh = 12;
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.rgb(18, 27, 50));
            c.drawRoundRect(new RectF(l, top, l+bw, top+bh), 8, 8, p);
            float shown = Math.max(0, Math.min(99.4f, progress));
            if (shown > 0) {
                p.setShader(new LinearGradient(l, 0, l+bw, 0,
                        Color.rgb(53, 230, 255), Color.rgb(178, 75, 255), Shader.TileMode.CLAMP));
                c.drawRoundRect(new RectF(l, top, l+bw*(shown/100f), top+bh), 8, 8, p);
                p.setShader(null);
            }
            text(c, String.format("STABILITY %.1f%%", shown), l, top+35, 12, Color.rgb(190, 204, 229), Paint.Align.LEFT, true);
            int ec = energy > 55 ? Color.rgb(100, 245, 210) : energy > 25 ? Color.rgb(255, 190, 80) : Color.rgb(255, 76, 108);
            text(c, "CORE " + Math.max(0, (int)energy), w-26, top+35, 12, ec, Paint.Align.RIGHT, true);

            text(c, "COMBO", 26, h-72, 11, Color.rgb(117, 135, 166), Paint.Align.LEFT, true);
            text(c, "x"+combo, 26, h-38, 28, Color.WHITE, Paint.Align.LEFT, true);
            text(c, status, w-26, h-43, 14, Color.rgb(105, 232, 255), Paint.Align.RIGHT, true);
        }

        private void drawReactor(Canvas c) {
            float core = Math.min(w, h) * .13f;
            float target = core * 1.75f;
            float pulseR = core * (.72f + pulse * 1.66f);

            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(20f);
            p.setColor(Color.argb(28, 75, 223, 255));
            c.drawCircle(cx, cy, target, p);

            RectF tr = new RectF(cx-target, cy-target, cx+target, cy+target);
            p.setStrokeWidth(5f);
            p.setColor(Color.rgb(108, 239, 255));
            c.drawArc(tr, ringA, 72, false, p);
            c.drawArc(tr, ringA+118, 44, false, p);
            c.drawArc(tr, ringA+238, 68, false, p);

            float r2 = core*2.18f;
            RectF r2f = new RectF(cx-r2,cy-r2,cx+r2,cy+r2);
            p.setStrokeWidth(3f);
            p.setColor(Color.argb(110, 126, 137, 177));
            for (int i=0;i<6;i++) c.drawArc(r2f, ringB+i*60f, 27f, false, p);

            float r3 = core*2.55f;
            p.setStrokeWidth(2f);
            p.setColor(Color.argb(80, 78, 210, 255));
            c.drawCircle(cx,cy,r3,p);
            p.setStyle(Paint.Style.FILL);
            for (int i=0;i<8;i++) {
                double a = Math.toRadians(ringA + i*45f);
                c.drawCircle(cx+(float)Math.cos(a)*r3, cy+(float)Math.sin(a)*r3, 4f, p);
            }

            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(5f);
            p.setColor(Color.rgb(225, 160, 255));
            c.drawCircle(cx, cy, pulseR, p);

            p.setStyle(Paint.Style.FILL);
            p.setShader(new RadialGradient(cx,cy,core*1.5f,
                    new int[]{Color.argb(160,90,240,255), Color.argb(65,70,120,255), Color.TRANSPARENT},
                    null, Shader.TileMode.CLAMP));
            c.drawCircle(cx,cy,core*1.5f,p);
            p.setShader(null);

            p.setShader(new RadialGradient(cx,cy,core,
                    new int[]{Color.WHITE, Color.rgb(80,235,255), Color.rgb(39,95,200), Color.rgb(12,21,64)},
                    new float[]{0f,.18f,.62f,1f}, Shader.TileMode.CLAMP));
            c.drawCircle(cx,cy,core,p);
            p.setShader(null);

            text(c, String.format("%.0f%%", Math.min(99f, progress)), cx, cy+8, 26, Color.rgb(5,18,38), Paint.Align.CENTER, true);
            text(c, "TAP ON SYNC", cx, cy+core*3.25f, 12, Color.rgb(145,163,193), Paint.Align.CENTER, true);
        }

        private void drawParticles(Canvas c) {
            p.setShader(null);
            p.setStyle(Paint.Style.FILL);
            for (Particle q : particles) {
                float a = Math.max(0f, Math.min(1f, q.life/q.maxLife));
                p.setColor(alpha(q.color,a));
                c.drawCircle(q.x,q.y,q.size*(.45f+a),p);
            }
        }

        private void drawTexts(Canvas c) {
            for (FloatingText f : texts) {
                float a = Math.max(0f, Math.min(1f, f.life/f.maxLife));
                text(c,f.s,f.x,f.y,f.size,alpha(f.color,a),Paint.Align.CENTER,true);
            }
        }

        private void drawDead(Canvas c) {
            p.setShader(null);
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.argb(190, 2, 4, 14));
            c.drawRect(0,0,w,h,p);
            float cw=w*.84f, ch=Math.min(330f,h*.42f);
            RectF card=new RectF(cx-cw/2f,cy-ch/2f,cx+cw/2f,cy+ch/2f);
            p.setColor(Color.rgb(11,17,36));
            c.drawRoundRect(card,30,30,p);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(2.5f);
            p.setColor(Color.rgb(255,73,107));
            c.drawRoundRect(card,30,30,p);
            text(c,"REACTOR LOST",cx,card.top+58,15,Color.rgb(255,84,115),Paint.Align.CENTER,true);
            text(c,failReason,cx,card.top+105,21,Color.WHITE,Paint.Align.CENTER,true);
            text(c,String.format("وصلت إلى %.1f%%",Math.min(99.4f,progress)),cx,card.top+153,16,Color.rgb(184,198,222),Paint.Align.CENTER,false);
            text(c,"BEST COMBO x"+bestCombo,cx,card.top+195,13,Color.rgb(105,235,255),Paint.Align.CENTER,true);
            RectF retry=new RectF(card.left+36,card.bottom-69,card.right-36,card.bottom-18);
            p.setStyle(Paint.Style.FILL);
            p.setColor(Color.rgb(45,205,235));
            c.drawRoundRect(retry,16,16,p);
            text(c,"إعادة المحاولة",cx,retry.centerY()+6,16,Color.rgb(5,15,28),Paint.Align.CENTER,true);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (e.getAction()!=MotionEvent.ACTION_DOWN) return true;
            if (state==MENU || state==DEAD) { startRun(); return true; }
            handleTap(e.getX(),e.getY());
            return true;
        }

        private void startRun() {
            state=PLAY;
            run++;
            progress=0;
            energy=100;
            combo=0;
            pulse=.08f+rng.nextFloat()*.3f;
            targetFail=88.5f+rng.nextFloat()*10f;
            status="SYNC READY";
            failReason="";
            particles.clear();
            texts.clear();
            burst(cx,cy,45,Color.rgb(85,235,255),300f);
            haptic(20);
        }

        private void handleTap(float x,float y) {
            float core=Math.min(w,h)*.13f;
            float target=core*1.75f;
            float pulseR=core*(.72f+pulse*1.66f);
            float err=Math.abs(pulseR-target);
            float perfect=core*.18f;
            float good=core*.42f;

            if (err<=perfect) {
                combo++;
                bestCombo=Math.max(bestCombo,combo);
                float gain=8.4f+Math.min(5.6f,combo*.38f);
                progress+=gain;
                energy=Math.min(100f,energy+3.5f);
                status=combo>=4?"PERFECT CHAIN x"+combo:"PERFECT SYNC";
                texts.add(new FloatingText("PERFECT +"+(int)gain,cx,cy-42,18,Color.rgb(110,255,215)));
                burst(cx,cy,36,Color.rgb(100,255,215),340f);
                shake=Math.max(shake,4f);
                haptic(24);
            } else if (err<=good) {
                combo++;
                bestCombo=Math.max(bestCombo,combo);
                float gain=4.2f+Math.min(2.6f,combo*.18f);
                progress+=gain;
                status="SYNC +"+(int)gain;
                texts.add(new FloatingText("GOOD +"+(int)gain,cx,cy-38,16,Color.rgb(105,220,255)));
                burst(cx,cy,22,Color.rgb(82,214,255),250f);
                haptic(14);
            } else {
                combo=0;
                energy-=13.5f;
                progress=Math.max(0,progress-2.1f);
                status="DESYNC";
                texts.add(new FloatingText("DESYNC -2",x,y,16,Color.rgb(255,90,120)));
                burst(x,y,22,Color.rgb(255,74,108),220f);
                flash=.16f;
                shake=Math.max(shake,13f);
                haptic(42);
            }

            // No win path exists. Every run is deliberately stopped before 100%.
            if (progress>=targetFail) {
                progress=Math.min(99.4f,Math.max(progress,96.1f+rng.nextFloat()*3.2f));
                fail(failures[rng.nextInt(failures.length)]);
            } else if (energy<=0f) {
                fail("CORE COLLAPSE");
            }
        }

        private void fail(String reason) {
            if (state!=PLAY) return;
            state=DEAD;
            failReason=reason;
            combo=0;
            flash=1f;
            shake=38f;
            burst(cx,cy,120,Color.rgb(255,66,101),650f);
            burst(cx,cy,70,Color.rgb(142,75,255),470f);
            haptic(120);
        }

        private void burst(float x,float y,int count,int color,float speed) {
            for (int i=0;i<count;i++) {
                double a=rng.nextFloat()*Math.PI*2;
                float s=speed*(.18f+rng.nextFloat()*.82f);
                particles.add(new Particle(x,y,(float)Math.cos(a)*s,(float)Math.sin(a)*s,2f+rng.nextFloat()*5f,.35f+rng.nextFloat()*.65f,color));
            }
        }

        private void haptic(long ms) {
            try { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); } catch (Throwable ignored) {}
            try {
                if (vibrator==null || !vibrator.hasVibrator()) return;
                if (Build.VERSION.SDK_INT>=26) vibrator.vibrate(VibrationEffect.createOneShot(ms,VibrationEffect.DEFAULT_AMPLITUDE));
                else vibrator.vibrate(ms);
            } catch (Throwable ignored) {}
        }

        private void text(Canvas c,String s,float x,float y,float sp,int color,Paint.Align align,boolean bold) {
            p.setShader(null);
            p.setStyle(Paint.Style.FILL);
            p.setTextAlign(align);
            p.setTextSize(sp*getResources().getDisplayMetrics().scaledDensity);
            p.setColor(color);
            p.setTypeface(android.graphics.Typeface.create("sans",bold?android.graphics.Typeface.BOLD:android.graphics.Typeface.NORMAL));
            c.drawText(s,x,y,p);
        }

        private int alpha(int color,float a) {
            return Color.argb((int)(255*Math.max(0f,Math.min(1f,a))),Color.red(color),Color.green(color),Color.blue(color));
        }

        static final class Particle {
            float x,y,vx,vy,size,life,maxLife; int color;
            Particle(float x,float y,float vx,float vy,float size,float life,int color) {
                this.x=x; this.y=y; this.vx=vx; this.vy=vy; this.size=size; this.life=life; this.maxLife=life; this.color=color;
            }
        }

        static final class FloatingText {
            String s; float x,y,size,life,maxLife; int color;
            FloatingText(String s,float x,float y,float size,int color) {
                this.s=s; this.x=x; this.y=y; this.size=size; this.life=.85f; this.maxLife=.85f; this.color=color;
            }
        }
    }
}
