package com.example.impossiblegame;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Random;

public class MainActivity extends Activity {
    private final Random random = new Random();
    private final Handler handler = new Handler();
    private FrameLayout arena;
    private Button target;
    private TextView attemptsText;
    private TextView statusText;
    private TextView recordText;
    private int attempts = 0;

    private final String[] messages = {
            "قريب... بصح خسرت 😏",
            "كنت رايح تلحقها 😂",
            "لا لا، أسرع من هك!",
            "الزر شافك وجبد روحو 😎",
            "محاولة مليحة... النتيجة نفسها: خسارة",
            "راك قريب بزاف... وهذا هو المشكل",
            "حتى هذي ما تحسبش 😌",
            "المرة الجاية؟ نفس الشيء."
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(17, 17, 17));
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        LinearLayout topPanel = new LinearLayout(this);
        topPanel.setOrientation(LinearLayout.VERTICAL);
        topPanel.setGravity(Gravity.CENTER);
        topPanel.setPadding(dp(18), dp(20), dp(18), dp(12));

        TextView title = makeText("اللعبة المستحيلة", 28, true);
        TextView subtitle = makeText("الهدف بسيط: اضغط الزر.\nالمشكل؟ مستحيل تربح.", 16, false);
        attemptsText = makeText("المحاولات: 0", 18, true);
        recordText = makeText("الانتصارات: 0", 16, false);
        statusText = makeText("ابدأ أول محاولة 👇", 18, true);

        topPanel.addView(title);
        topPanel.addView(subtitle);
        topPanel.addView(attemptsText);
        topPanel.addView(recordText);
        topPanel.addView(statusText);

        FrameLayout.LayoutParams topParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
        );
        topParams.gravity = Gravity.TOP;
        root.addView(topPanel, topParams);

        arena = new FrameLayout(this);
        arena.setBackgroundColor(Color.rgb(30, 30, 30));
        FrameLayout.LayoutParams arenaParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        );
        arenaParams.setMargins(dp(14), dp(230), dp(14), dp(18));
        root.addView(arena, arenaParams);

        target = new Button(this);
        target.setText("اضغطني واربح");
        target.setTextSize(18);
        target.setTypeface(Typeface.DEFAULT_BOLD);
        target.setTextColor(Color.WHITE);
        target.setBackgroundColor(Color.rgb(220, 45, 45));
        target.setAllCaps(false);

        FrameLayout.LayoutParams targetParams = new FrameLayout.LayoutParams(dp(170), dp(68));
        targetParams.gravity = Gravity.CENTER;
        arena.addView(target, targetParams);

        target.setOnTouchListener((v, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                loseAttempt();
                moveTarget();
                v.performHapticFeedback(android.view.HapticFeedbackConstants.REJECT);
                return true;
            }
            return true;
        });

        target.setOnClickListener(v -> {
            loseAttempt();
            moveTarget();
        });

        arena.setOnTouchListener((v, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                loseAttempt();
                moveTarget();
                return true;
            }
            return true;
        });

        setContentView(root);
        arena.postDelayed(this::moveTarget, 450);
    }

    private void loseAttempt() {
        attempts++;
        attemptsText.setText("المحاولات: " + attempts);
        recordText.setText("الانتصارات: 0");
        statusText.setText(messages[random.nextInt(messages.length)]);
        if (attempts % 7 == 0) {
            statusText.setText("خسرت الجولة بالكامل 😈");
            target.setText("عاود جرّب");
            handler.postDelayed(() -> target.setText("اضغطني واربح"), 1100);
        }
    }

    private void moveTarget() {
        if (arena == null || target == null) return;
        int maxX = arena.getWidth() - target.getWidth() - dp(16);
        int maxY = arena.getHeight() - target.getHeight() - dp(16);
        if (maxX <= dp(16) || maxY <= dp(16)) return;
        int x = dp(8) + random.nextInt(Math.max(1, maxX - dp(8)));
        int y = dp(8) + random.nextInt(Math.max(1, maxY - dp(8)));
        target.animate().x(x).y(y).rotationBy(random.nextBoolean() ? 4f : -4f).setDuration(90).start();
    }

    private TextView makeText(String text, int sp, boolean bold) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(sp);
        tv.setGravity(Gravity.CENTER);
        tv.setPadding(dp(6), dp(5), dp(6), dp(5));
        if (bold) tv.setTypeface(Typeface.DEFAULT_BOLD);
        return tv;
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }
}
