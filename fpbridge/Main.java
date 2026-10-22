package com.nx.fpb;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import android.util.Log;

public class Main extends Activity {
    static final String T = "FPBRIDGE";
    static final String DESC = "com.fingerprint.sensorservice.IUdfpsMessageService";
    IBinder mSvc;

    final ServiceConnection mConn = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName n, IBinder b) {
            mSvc = b;
            Log.i(T, "connected: " + n.flattenToShortString());
            int msg = getIntent().getIntExtra("msg", 6);
            int info = getIntent().getIntExtra("info", 0);
            int color = getIntent().getIntExtra("color", 0xff000000);
            send(msg, info, color);
        }
        @Override public void onServiceDisconnected(ComponentName n) { mSvc = null; }
    };

    void send(int msg, int info, int color) {
        if (mSvc == null) { Log.e(T, "svc null"); return; }
        Parcel d = Parcel.obtain();
        Parcel r = Parcel.obtain();
        try {
            d.writeInterfaceToken(DESC);
            d.writeInt(msg);
            d.writeInt(info);
            d.writeInt(color);
            boolean ok = mSvc.transact(1, d, r, 0);
            r.readException();
            Log.i(T, "transact ok=" + ok + " msg=" + msg + " info=" + info + " color=" + Integer.toHexString(color));
        } catch (Throwable e) {
            Log.e(T, "transact failed", e);
        } finally {
            d.recycle(); r.recycle();
        }
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Intent i = new Intent();
        i.setClassName("com.fingerprint.sensorservice", "com.fingerprint.sensorservice.UdfpsMessageService");
        boolean ok = bindService(i, mConn, Context.BIND_AUTO_CREATE);
        Log.i(T, "bindService=" + ok);
        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override public void run() { finish(); }
        }, 1500);
    }
}
