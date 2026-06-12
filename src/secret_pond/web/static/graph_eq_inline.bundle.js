var SecretPondGraphEqBundle = (() => {
  // node_modules/weq8c/dist/package.ff5abd4b.js
  var C = () => ({
    events: {},
    emit(e8, ...s5) {
      let t5 = this.events[e8] || [];
      for (let n7 = 0, a3 = t5.length; n7 < a3; n7++)
        t5[n7](...s5);
    },
    on(e8, s5) {
      var t5;
      return (t5 = this.events[e8]) != null && t5.push(s5) || (this.events[e8] = [s5]), () => {
        var n7;
        this.events[e8] = (n7 = this.events[e8]) == null ? void 0 : n7.filter((a3) => s5 !== a3);
      };
    }
  });
  var Q = [
    "lowpass12",
    "lowpass24",
    "highpass12",
    "highpass24",
    "bandpass12",
    "bandpass24",
    "lowshelf12",
    "lowshelf24",
    "highshelf12",
    "highshelf24",
    "peaking12",
    "peaking24",
    "notch12",
    "notch24"
  ];
  var A = [
    { type: "lowshelf12", frequency: 30, gain: 0, Q: 0.7, bypass: false },
    { type: "peaking12", frequency: 200, gain: 0, Q: 0.7, bypass: false },
    { type: "peaking12", frequency: 1e3, gain: 0, Q: 0.7, bypass: false },
    { type: "highshelf12", frequency: 5e3, gain: 0, Q: 0.7, bypass: false },
    { type: "noop", frequency: 350, gain: 0, Q: 1, bypass: false },
    { type: "noop", frequency: 350, gain: 0, Q: 1, bypass: false },
    { type: "noop", frequency: 350, gain: 0, Q: 1, bypass: false },
    { type: "noop", frequency: 350, gain: 0, Q: 1, bypass: false }
  ];
  function r(e8) {
    return e8.type !== "noop";
  }
  function M(e8, s5) {
    if (s5 < 0 || s5 >= e8.length || !r(e8[s5]))
      return null;
    let t5 = 0;
    for (let n7 = 0; n7 <= s5; n7++)
      r(e8[n7]) && t5++;
    return t5;
  }
  function S(e8, s5) {
    const t5 = e8.map((o7, c3) => o7.type !== "noop" ? c3 : -1).filter((o7) => o7 !== -1);
    let n7 = 0, a3 = 7;
    return t5.length > 0 && (n7 = t5[0], a3 = t5[t5.length - 1]), s5 === 0 || s5 === n7 ? "lowshelf12" : s5 >= a3 ? "highshelf12" : "peaking12";
  }
  function j(e8, s5, t5) {
    return s5 === t5 ? `${e8} \u2605` : e8;
  }
  function E(e8) {
    return e8 === "lowshelf12" || e8 === "lowshelf24" || e8 === "highshelf12" || e8 === "highshelf24" || e8 === "peaking12" || e8 === "peaking24";
  }
  function L(e8) {
    return e8 !== "noop";
  }
  function x(e8) {
    return e8 === "lowpass12" || e8 === "lowpass24" || e8 === "highpass12" || e8 === "highpass24" || e8 === "bandpass12" || e8 === "bandpass24" || e8 === "peaking12" || e8 === "peaking24" || e8 === "notch12" || e8 === "notch24";
  }
  function H(e8) {
    switch (e8) {
      case "lowpass12":
      case "lowpass24":
        return "lowpass";
      case "highpass12":
      case "highpass24":
        return "highpass";
      case "bandpass12":
      case "bandpass24":
        return "bandpass";
      case "lowshelf12":
      case "lowshelf24":
        return "lowshelf";
      case "highshelf12":
      case "highshelf24":
        return "highshelf";
      case "peaking12":
      case "peaking24":
        return "peaking";
      case "notch12":
      case "notch24":
        return "notch";
    }
  }
  function T(e8) {
    switch (e8) {
      case "noop":
        return 0;
      case "lowpass12":
      case "highpass12":
      case "bandpass12":
      case "lowshelf12":
      case "highshelf12":
      case "peaking12":
      case "notch12":
        return 1;
      case "lowpass24":
      case "highpass24":
      case "bandpass24":
      case "lowshelf24":
      case "highshelf24":
      case "peaking24":
      case "notch24":
        return 2;
    }
  }
  function D(e8, s5, t5) {
    let n7 = Math.log10(s5), a3 = Math.log10(t5);
    return (Math.log10(i(e8, s5, t5)) - n7) / (a3 - n7);
  }
  function B(e8, s5, t5) {
    let n7 = Math.log10(s5), a3 = Math.log10(t5);
    return i(Math.pow(10, e8 * (a3 - n7) + n7), s5, t5);
  }
  function i(e8, s5, t5) {
    return Math.min(Math.max(e8, s5), t5);
  }
  function R(e8, s5 = false) {
    return e8 >= 1e3 && !s5 ? (e8 / 1e3).toFixed(2) : e8.toFixed(0);
  }
  function W(e8, s5 = false) {
    return e8 >= 1e3 && !s5 ? "kHz" : "Hz";
  }
  function z(e8, s5) {
    const t5 = new Float32Array(e8);
    for (let n7 = 0; n7 < e8; n7++) {
      const a3 = n7 / (e8 - 1) * 2 - 1;
      t5[n7] = i(a3, -s5, s5);
    }
    return t5;
  }
  function I(e8, s5) {
    const t5 = new Float32Array(e8);
    for (let n7 = 0; n7 < e8; n7++) {
      const a3 = n7 / (e8 - 1) * 2 - 1;
      t5[n7] = Math.tanh(a3 / s5) * s5;
    }
    return t5;
  }
  function K(e8, s5) {
    const t5 = new Float32Array(e8);
    for (let n7 = 0; n7 < e8; n7++) {
      let a3 = n7 / (e8 - 1) * 2 - 1;
      a3 > s5 ? a3 = 2 * s5 - a3 : a3 < -s5 && (a3 = -2 * s5 - a3), t5[n7] = i(a3, -1, 1);
    }
    return t5;
  }
  var l = "weq8c";
  var u = "0.3.5";
  var p = "module";
  var h = "ISC";
  var f = "https://github.com/KRWCLASSIC/WEQ8C";
  var g = "KRWCLASSIC/WEQ8C";
  var d = {
    name: "krwclassic"
  };
  var y = {
    ".": {
      import: "./dist/runtime.js",
      require: "./dist/runtime.cjs"
    },
    "./ui": {
      import: "./dist/ui.js",
      require: "./dist/ui.cjs"
    }
  };
  var m = "./dist/runtime.cjs";
  var w = "./dist/runtime.js";
  var b = "./dist/main.d.ts";
  var v = [
    "dist"
  ];
  var k = {
    dev: "vite",
    build: "tsc && vite build",
    "build:watch": "tsc && vite build --watch"
  };
  var F = {
    lit: "^2.4.0",
    nanoevents: "^7.0.1"
  };
  var q = {
    "@rollup/plugin-typescript": "^9.0.2",
    "@types/node": "^18.11.9",
    "rollup-plugin-typescript-paths": "^1.4.0",
    tslib: "^2.4.1",
    typescript: "^4.6.4",
    vite: "^3.2.3"
  };
  var N = {
    name: l,
    version: u,
    type: p,
    license: h,
    homepage: f,
    repository: g,
    author: d,
    exports: y,
    main: m,
    module: w,
    typings: b,
    files: v,
    scripts: k,
    dependencies: F,
    devDependencies: q
  };

  // node_modules/weq8c/dist/runtime.js
  var R2 = class {
    constructor(t5, e8 = A, s5 = Q) {
      this.audioCtx = t5, this.spec = e8, this.supportedFilterTypes = s5, this.filterbank = [], this.saturatorNode = null, this._saturationMode = "none", this._saturationThreshold = 1, this.debugAnalyser = null, this.input = t5.createGain(), this.output = t5.createGain(), this.debugAnalyser = t5.createAnalyser(), this.debugAnalyser.fftSize = 1024, this.output.connect(this.debugAnalyser), this.buildFilterChain(e8), this.emitter = C();
    }
    connect(t5) {
      this.output.connect(t5);
    }
    disconnect(t5) {
      this.output.disconnect(t5);
    }
    on(t5, e8) {
      return this.emitter.on(t5, e8);
    }
    get saturationMode() {
      return this._saturationMode;
    }
    get saturationThreshold() {
      return this._saturationThreshold;
    }
    get inputGain() {
      return this.input.gain.value;
    }
    set inputGain(t5) {
      this.input.gain.value = t5;
    }
    get outputGain() {
      return this.output.gain.value;
    }
    set outputGain(t5) {
      this.output.gain.value = t5;
    }
    setSaturationMode(t5, e8) {
      var i7;
      const s5 = (i7 = e8 == null ? void 0 : e8.threshold) != null ? i7 : 1;
      this._saturationMode = t5, this._saturationThreshold = s5, this.rebuildSaturatorConnection(), this.emitter.emit("saturationChanged", t5);
    }
    rebuildSaturatorConnection() {
      this.saturatorNode && (this.saturatorNode.disconnect(), this.saturatorNode = null);
      const t5 = this.getLastActiveSourceNode();
      try {
        t5.disconnect(this.output);
      } catch {
      }
      if (this._saturationMode === "none")
        t5.connect(this.output);
      else if (this._saturationMode === "limit") {
        const e8 = this.audioCtx.createDynamicsCompressor();
        e8.threshold.value = -0.1, e8.knee.value = 0, e8.ratio.value = 20, e8.attack.value = 3e-3, e8.release.value = 0.05, this.saturatorNode = e8, t5.connect(e8), e8.connect(this.output);
      } else {
        const e8 = this.audioCtx.createWaveShaper();
        e8.oversample = "4x";
        const s5 = 4096;
        this._saturationMode === "hard" ? e8.curve = z(s5, this._saturationThreshold) : this._saturationMode === "soft" ? e8.curve = I(s5, this._saturationThreshold) : this._saturationMode === "foldback" && (e8.curve = K(s5, this._saturationThreshold)), this.saturatorNode = e8, t5.connect(e8), e8.connect(this.output);
      }
    }
    getLastActiveSourceNode() {
      if (this.filterbank.length === 0)
        return this.input;
      const t5 = this.filterbank[this.filterbank.length - 1];
      return t5.filters[t5.filters.length - 1];
    }
    setFilterType(t5, e8) {
      var s5;
      if (e8 === "noop" && this.spec[t5].type !== "noop" && !this.spec[t5].bypass && this.disconnectFilter(t5), e8 === "noop" ? this.spec[t5].bypass = false : this.spec[t5].type === "noop" && (this.spec[t5].bypass = false, this.connectFilter(t5, e8)), this.spec[t5].type = e8, e8 !== "noop" && !this.spec[t5].bypass) {
        let i7 = (s5 = this.filterbank.find((n7) => n7.idx === t5)) == null ? void 0 : s5.filters;
        if (!i7)
          throw new Error("Assertion failed: No filters in filterbank");
        for (let n7 of i7)
          n7.type = H(e8);
        let r5 = T(e8);
        for (; i7.length > r5; ) {
          let n7 = i7.length - 1, o7 = i7[n7], h4 = i7[n7 - 1], f3 = this.getNextInChain(t5);
          o7.disconnect(), h4.disconnect(o7), h4.connect(f3), i7.splice(n7, 1);
        }
        for (; i7.length < r5; ) {
          let n7 = this.audioCtx.createBiquadFilter();
          n7.type = H(e8), n7.frequency.value = this.spec[t5].frequency, n7.Q.value = this.spec[t5].Q, n7.gain.value = this.spec[t5].gain;
          let o7 = i7[i7.length - 1], h4 = this.getNextInChain(t5);
          o7.disconnect(h4), o7.connect(n7), n7.connect(h4), i7.push(n7);
        }
      }
      this.emitter.emit("filtersChanged", this.spec);
    }
    toggleBypass(t5, e8) {
      e8 && !this.spec[t5].bypass && this.spec[t5].type !== "noop" ? this.disconnectFilter(t5) : !e8 && this.spec[t5].bypass && this.spec[t5].type !== "noop" && this.connectFilter(t5, this.spec[t5].type), this.spec[t5].bypass = e8, this.emitter.emit("filtersChanged", this.spec);
    }
    disconnectFilter(t5) {
      var r5;
      let e8 = (r5 = this.filterbank.find((n7) => n7.idx === t5)) == null ? void 0 : r5.filters;
      if (!e8)
        throw new Error(
          "Assertion failed: No filters in filterbank when disconnecting filter. Was it connected?"
        );
      let s5 = this.getPreviousInChain(t5), i7 = this.getNextInChain(t5);
      s5.disconnect(e8[0]), e8[e8.length - 1].disconnect(i7), s5.connect(i7), this.filterbank = this.filterbank.filter((n7) => n7.idx !== t5), this.rebuildSaturatorConnection();
    }
    connectFilter(t5, e8) {
      let s5 = Array.from({ length: T(e8) }, () => {
        let n7 = this.audioCtx.createBiquadFilter();
        return n7.type = H(e8), n7.frequency.value = this.spec[t5].frequency, n7.Q.value = this.spec[t5].Q, n7.gain.value = this.spec[t5].gain, n7;
      }), i7 = this.getPreviousInChain(t5), r5 = this.getNextInChain(t5);
      i7.disconnect(r5), i7.connect(s5[0]);
      for (let n7 = 0; n7 < s5.length - 1; n7++)
        s5[n7].connect(s5[n7 + 1]);
      s5[s5.length - 1].connect(r5), this.filterbank.push({ idx: t5, filters: s5 }), this.filterbank.sort((n7, o7) => n7.idx - o7.idx), this.rebuildSaturatorConnection();
    }
    setFilterFrequency(t5, e8) {
      this.spec[t5].frequency = e8;
      let s5 = this.filterbank.find((i7) => i7.idx === t5);
      if (s5)
        for (let i7 of s5.filters)
          i7.frequency.value = e8;
      this.emitter.emit("filtersChanged", this.spec);
    }
    setFilterQ(t5, e8) {
      this.spec[t5].Q = e8;
      let s5 = this.filterbank.find((i7) => i7.idx === t5);
      if (s5)
        for (let i7 of s5.filters)
          i7.Q.value = e8;
      this.emitter.emit("filtersChanged", this.spec);
    }
    setFilterGain(t5, e8) {
      this.spec[t5].gain = e8;
      let s5 = this.filterbank.find((i7) => i7.idx === t5);
      if (s5)
        for (let i7 of s5.filters)
          i7.gain.value = e8;
      this.emitter.emit("filtersChanged", this.spec);
    }
    getEqResponseAtFrequency(t5) {
      const e8 = new Float32Array([t5]), s5 = new Float32Array(1), i7 = new Float32Array(1);
      let r5 = 1, n7 = 0;
      for (let o7 = 0; o7 < this.spec.length; o7++) {
        if (this.spec[o7].type === "noop" || this.spec[o7].bypass)
          continue;
        const h4 = T(this.spec[o7].type);
        for (let f3 = 0; f3 < h4; f3++)
          this.getFrequencyResponse(
            o7,
            f3,
            e8,
            s5,
            i7
          ) && (r5 *= s5[0], n7 += i7[0]);
      }
      return {
        magnitudeDb: r5 > 0 ? 20 * Math.log10(r5) : -96,
        phaseDeg: n7 * 180 / Math.PI
      };
    }
    getFrequencyResponse(t5, e8, s5, i7, r5) {
      let n7 = this.filterbank.find((o7) => o7.idx === t5);
      return n7 ? (n7.filters[e8].getFrequencyResponse(
        s5,
        i7,
        r5
      ), true) : false;
    }
    getDebugStats() {
      const e8 = new Float32Array(512), s5 = this.audioCtx.sampleRate / 2, i7 = Math.log10(20), r5 = Math.log10(s5);
      for (let a3 = 0; a3 < 512; a3++) {
        const l6 = i7 + a3 / 511 * (r5 - i7);
        e8[a3] = Math.pow(10, l6);
      }
      const n7 = new Float32Array(512), o7 = new Float32Array(512);
      n7.fill(1), o7.fill(0);
      const h4 = new Float32Array(512), f3 = new Float32Array(512);
      let m3 = 0, k4 = 0;
      for (let a3 = 0; a3 < this.spec.length; a3++) {
        if (this.spec[a3].type === "noop" || this.spec[a3].bypass)
          continue;
        m3++;
        const l6 = T(this.spec[a3].type);
        k4 += l6;
        for (let p3 = 0; p3 < l6; p3++)
          if (this.getFrequencyResponse(a3, p3, e8, h4, f3))
            for (let c3 = 0; c3 < 512; c3++)
              n7[c3] *= h4[c3], o7[c3] += f3[c3];
      }
      let b4 = 0, y3 = 1 / 0, C3 = 0, A4 = 0, F2 = 0;
      for (let a3 = 0; a3 < 512; a3++) {
        const l6 = n7[a3];
        l6 > b4 && (b4 = l6, C3 = e8[a3]), l6 < y3 && (y3 = l6, A4 = e8[a3]);
        const p3 = Math.abs(o7[a3]);
        p3 > F2 && (F2 = p3);
      }
      const T4 = b4 > 0 ? 20 * Math.log10(b4) : -96, D3 = y3 > 0 ? 20 * Math.log10(y3) : -96, x3 = F2 * 180 / Math.PI;
      let M3 = -96, q2 = 0, w3 = false;
      if (this.debugAnalyser) {
        const a3 = new Float32Array(this.debugAnalyser.fftSize);
        this.debugAnalyser.getFloatTimeDomainData(a3);
        let l6 = 0;
        for (let u4 = 0; u4 < a3.length; u4++) {
          const _2 = Math.abs(a3[u4]);
          _2 > l6 && (l6 = _2);
        }
        l6 > 0 && (M3 = 20 * Math.log10(l6));
        const p3 = this._saturationMode === "none" ? 1 : this._saturationThreshold;
        w3 = l6 >= p3;
        const d4 = new Float32Array(this.debugAnalyser.frequencyBinCount);
        this.debugAnalyser.getFloatFrequencyData(d4);
        let c3 = -1 / 0, N3 = 0;
        for (let u4 = 0; u4 < d4.length; u4++)
          d4[u4] > c3 && (c3 = d4[u4], N3 = u4);
        q2 = N3 * this.audioCtx.sampleRate / this.debugAnalyser.fftSize;
      }
      return {
        curveMaxDb: T4,
        curveMaxDbFreq: C3,
        curveMinDb: D3,
        curveMinDbFreq: A4,
        curveMaxPhase: x3,
        activeBandsCount: m3,
        totalBiquadNodes: k4,
        audioMaxDb: M3,
        audioMaxDbFreq: q2,
        isClipping: w3,
        version: R2.version,
        inputGain: this.inputGain,
        outputGain: this.outputGain
      };
    }
    buildFilterChain(t5) {
      this.filterbank = [];
      for (let e8 = 0; e8 < t5.length; e8++) {
        let s5 = t5[e8];
        if (s5.type === "noop" || s5.bypass)
          continue;
        let i7 = Array.from(
          { length: T(s5.type) },
          () => {
            let r5 = this.audioCtx.createBiquadFilter();
            return r5.type = H(s5.type), r5.frequency.value = s5.frequency, r5.Q.value = s5.Q, r5.gain.value = s5.gain, r5;
          }
        );
        this.filterbank.push({ idx: e8, filters: i7 });
      }
      if (this.filterbank.length > 0)
        for (let e8 = 0; e8 < this.filterbank.length; e8++) {
          let { filters: s5 } = this.filterbank[e8];
          e8 === 0 ? this.input.connect(s5[0]) : this.filterbank[e8 - 1].filters[this.filterbank[e8 - 1].filters.length - 1].connect(s5[0]);
          for (let i7 = 0; i7 < s5.length - 1; i7++)
            s5[i7].connect(s5[i7 + 1]);
        }
      this.rebuildSaturatorConnection();
    }
    getPreviousInChain(t5) {
      let e8 = this.input, s5 = -1;
      for (let i7 of this.filterbank)
        i7.idx < t5 && i7.idx > s5 && (e8 = i7.filters[i7.filters.length - 1], s5 = i7.idx);
      return e8;
    }
    getNextInChain(t5) {
      let e8 = this.saturatorNode || this.output, s5 = this.spec.length;
      for (let i7 of this.filterbank)
        i7.idx > t5 && i7.idx < s5 && (e8 = i7.filters[0], s5 = i7.idx);
      return e8;
    }
  };
  var Q2 = R2;
  Q2.version = N.version;

  // node_modules/@lit/reactive-element/css-tag.js
  var t = window;
  var e = t.ShadowRoot && (void 0 === t.ShadyCSS || t.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype;
  var s = Symbol();
  var n = /* @__PURE__ */ new WeakMap();
  var o = class {
    constructor(t5, e8, n7) {
      if (this._$cssResult$ = true, n7 !== s) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
      this.cssText = t5, this.t = e8;
    }
    get styleSheet() {
      let t5 = this.o;
      const s5 = this.t;
      if (e && void 0 === t5) {
        const e8 = void 0 !== s5 && 1 === s5.length;
        e8 && (t5 = n.get(s5)), void 0 === t5 && ((this.o = t5 = new CSSStyleSheet()).replaceSync(this.cssText), e8 && n.set(s5, t5));
      }
      return t5;
    }
    toString() {
      return this.cssText;
    }
  };
  var r2 = (t5) => new o("string" == typeof t5 ? t5 : t5 + "", void 0, s);
  var i2 = (t5, ...e8) => {
    const n7 = 1 === t5.length ? t5[0] : e8.reduce(((e9, s5, n8) => e9 + ((t6) => {
      if (true === t6._$cssResult$) return t6.cssText;
      if ("number" == typeof t6) return t6;
      throw Error("Value passed to 'css' function must be a 'css' function result: " + t6 + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
    })(s5) + t5[n8 + 1]), t5[0]);
    return new o(n7, t5, s);
  };
  var S2 = (s5, n7) => {
    e ? s5.adoptedStyleSheets = n7.map(((t5) => t5 instanceof CSSStyleSheet ? t5 : t5.styleSheet)) : n7.forEach(((e8) => {
      const n8 = document.createElement("style"), o7 = t.litNonce;
      void 0 !== o7 && n8.setAttribute("nonce", o7), n8.textContent = e8.cssText, s5.appendChild(n8);
    }));
  };
  var c = e ? (t5) => t5 : (t5) => t5 instanceof CSSStyleSheet ? ((t6) => {
    let e8 = "";
    for (const s5 of t6.cssRules) e8 += s5.cssText;
    return r2(e8);
  })(t5) : t5;

  // node_modules/@lit/reactive-element/reactive-element.js
  var s2;
  var e2 = window;
  var r3 = e2.trustedTypes;
  var h2 = r3 ? r3.emptyScript : "";
  var o2 = e2.reactiveElementPolyfillSupport;
  var n2 = { toAttribute(t5, i7) {
    switch (i7) {
      case Boolean:
        t5 = t5 ? h2 : null;
        break;
      case Object:
      case Array:
        t5 = null == t5 ? t5 : JSON.stringify(t5);
    }
    return t5;
  }, fromAttribute(t5, i7) {
    let s5 = t5;
    switch (i7) {
      case Boolean:
        s5 = null !== t5;
        break;
      case Number:
        s5 = null === t5 ? null : Number(t5);
        break;
      case Object:
      case Array:
        try {
          s5 = JSON.parse(t5);
        } catch (t6) {
          s5 = null;
        }
    }
    return s5;
  } };
  var a = (t5, i7) => i7 !== t5 && (i7 == i7 || t5 == t5);
  var l2 = { attribute: true, type: String, converter: n2, reflect: false, hasChanged: a };
  var d2 = "finalized";
  var u2 = class extends HTMLElement {
    constructor() {
      super(), this._$Ei = /* @__PURE__ */ new Map(), this.isUpdatePending = false, this.hasUpdated = false, this._$El = null, this._$Eu();
    }
    static addInitializer(t5) {
      var i7;
      this.finalize(), (null !== (i7 = this.h) && void 0 !== i7 ? i7 : this.h = []).push(t5);
    }
    static get observedAttributes() {
      this.finalize();
      const t5 = [];
      return this.elementProperties.forEach(((i7, s5) => {
        const e8 = this._$Ep(s5, i7);
        void 0 !== e8 && (this._$Ev.set(e8, s5), t5.push(e8));
      })), t5;
    }
    static createProperty(t5, i7 = l2) {
      if (i7.state && (i7.attribute = false), this.finalize(), this.elementProperties.set(t5, i7), !i7.noAccessor && !this.prototype.hasOwnProperty(t5)) {
        const s5 = "symbol" == typeof t5 ? Symbol() : "__" + t5, e8 = this.getPropertyDescriptor(t5, s5, i7);
        void 0 !== e8 && Object.defineProperty(this.prototype, t5, e8);
      }
    }
    static getPropertyDescriptor(t5, i7, s5) {
      return { get() {
        return this[i7];
      }, set(e8) {
        const r5 = this[t5];
        this[i7] = e8, this.requestUpdate(t5, r5, s5);
      }, configurable: true, enumerable: true };
    }
    static getPropertyOptions(t5) {
      return this.elementProperties.get(t5) || l2;
    }
    static finalize() {
      if (this.hasOwnProperty(d2)) return false;
      this[d2] = true;
      const t5 = Object.getPrototypeOf(this);
      if (t5.finalize(), void 0 !== t5.h && (this.h = [...t5.h]), this.elementProperties = new Map(t5.elementProperties), this._$Ev = /* @__PURE__ */ new Map(), this.hasOwnProperty("properties")) {
        const t6 = this.properties, i7 = [...Object.getOwnPropertyNames(t6), ...Object.getOwnPropertySymbols(t6)];
        for (const s5 of i7) this.createProperty(s5, t6[s5]);
      }
      return this.elementStyles = this.finalizeStyles(this.styles), true;
    }
    static finalizeStyles(i7) {
      const s5 = [];
      if (Array.isArray(i7)) {
        const e8 = new Set(i7.flat(1 / 0).reverse());
        for (const i8 of e8) s5.unshift(c(i8));
      } else void 0 !== i7 && s5.push(c(i7));
      return s5;
    }
    static _$Ep(t5, i7) {
      const s5 = i7.attribute;
      return false === s5 ? void 0 : "string" == typeof s5 ? s5 : "string" == typeof t5 ? t5.toLowerCase() : void 0;
    }
    _$Eu() {
      var t5;
      this._$E_ = new Promise(((t6) => this.enableUpdating = t6)), this._$AL = /* @__PURE__ */ new Map(), this._$Eg(), this.requestUpdate(), null === (t5 = this.constructor.h) || void 0 === t5 || t5.forEach(((t6) => t6(this)));
    }
    addController(t5) {
      var i7, s5;
      (null !== (i7 = this._$ES) && void 0 !== i7 ? i7 : this._$ES = []).push(t5), void 0 !== this.renderRoot && this.isConnected && (null === (s5 = t5.hostConnected) || void 0 === s5 || s5.call(t5));
    }
    removeController(t5) {
      var i7;
      null === (i7 = this._$ES) || void 0 === i7 || i7.splice(this._$ES.indexOf(t5) >>> 0, 1);
    }
    _$Eg() {
      this.constructor.elementProperties.forEach(((t5, i7) => {
        this.hasOwnProperty(i7) && (this._$Ei.set(i7, this[i7]), delete this[i7]);
      }));
    }
    createRenderRoot() {
      var t5;
      const s5 = null !== (t5 = this.shadowRoot) && void 0 !== t5 ? t5 : this.attachShadow(this.constructor.shadowRootOptions);
      return S2(s5, this.constructor.elementStyles), s5;
    }
    connectedCallback() {
      var t5;
      void 0 === this.renderRoot && (this.renderRoot = this.createRenderRoot()), this.enableUpdating(true), null === (t5 = this._$ES) || void 0 === t5 || t5.forEach(((t6) => {
        var i7;
        return null === (i7 = t6.hostConnected) || void 0 === i7 ? void 0 : i7.call(t6);
      }));
    }
    enableUpdating(t5) {
    }
    disconnectedCallback() {
      var t5;
      null === (t5 = this._$ES) || void 0 === t5 || t5.forEach(((t6) => {
        var i7;
        return null === (i7 = t6.hostDisconnected) || void 0 === i7 ? void 0 : i7.call(t6);
      }));
    }
    attributeChangedCallback(t5, i7, s5) {
      this._$AK(t5, s5);
    }
    _$EO(t5, i7, s5 = l2) {
      var e8;
      const r5 = this.constructor._$Ep(t5, s5);
      if (void 0 !== r5 && true === s5.reflect) {
        const h4 = (void 0 !== (null === (e8 = s5.converter) || void 0 === e8 ? void 0 : e8.toAttribute) ? s5.converter : n2).toAttribute(i7, s5.type);
        this._$El = t5, null == h4 ? this.removeAttribute(r5) : this.setAttribute(r5, h4), this._$El = null;
      }
    }
    _$AK(t5, i7) {
      var s5;
      const e8 = this.constructor, r5 = e8._$Ev.get(t5);
      if (void 0 !== r5 && this._$El !== r5) {
        const t6 = e8.getPropertyOptions(r5), h4 = "function" == typeof t6.converter ? { fromAttribute: t6.converter } : void 0 !== (null === (s5 = t6.converter) || void 0 === s5 ? void 0 : s5.fromAttribute) ? t6.converter : n2;
        this._$El = r5, this[r5] = h4.fromAttribute(i7, t6.type), this._$El = null;
      }
    }
    requestUpdate(t5, i7, s5) {
      let e8 = true;
      void 0 !== t5 && (((s5 = s5 || this.constructor.getPropertyOptions(t5)).hasChanged || a)(this[t5], i7) ? (this._$AL.has(t5) || this._$AL.set(t5, i7), true === s5.reflect && this._$El !== t5 && (void 0 === this._$EC && (this._$EC = /* @__PURE__ */ new Map()), this._$EC.set(t5, s5))) : e8 = false), !this.isUpdatePending && e8 && (this._$E_ = this._$Ej());
    }
    async _$Ej() {
      this.isUpdatePending = true;
      try {
        await this._$E_;
      } catch (t6) {
        Promise.reject(t6);
      }
      const t5 = this.scheduleUpdate();
      return null != t5 && await t5, !this.isUpdatePending;
    }
    scheduleUpdate() {
      return this.performUpdate();
    }
    performUpdate() {
      var t5;
      if (!this.isUpdatePending) return;
      this.hasUpdated, this._$Ei && (this._$Ei.forEach(((t6, i8) => this[i8] = t6)), this._$Ei = void 0);
      let i7 = false;
      const s5 = this._$AL;
      try {
        i7 = this.shouldUpdate(s5), i7 ? (this.willUpdate(s5), null === (t5 = this._$ES) || void 0 === t5 || t5.forEach(((t6) => {
          var i8;
          return null === (i8 = t6.hostUpdate) || void 0 === i8 ? void 0 : i8.call(t6);
        })), this.update(s5)) : this._$Ek();
      } catch (t6) {
        throw i7 = false, this._$Ek(), t6;
      }
      i7 && this._$AE(s5);
    }
    willUpdate(t5) {
    }
    _$AE(t5) {
      var i7;
      null === (i7 = this._$ES) || void 0 === i7 || i7.forEach(((t6) => {
        var i8;
        return null === (i8 = t6.hostUpdated) || void 0 === i8 ? void 0 : i8.call(t6);
      })), this.hasUpdated || (this.hasUpdated = true, this.firstUpdated(t5)), this.updated(t5);
    }
    _$Ek() {
      this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = false;
    }
    get updateComplete() {
      return this.getUpdateComplete();
    }
    getUpdateComplete() {
      return this._$E_;
    }
    shouldUpdate(t5) {
      return true;
    }
    update(t5) {
      void 0 !== this._$EC && (this._$EC.forEach(((t6, i7) => this._$EO(i7, this[i7], t6))), this._$EC = void 0), this._$Ek();
    }
    updated(t5) {
    }
    firstUpdated(t5) {
    }
  };
  u2[d2] = true, u2.elementProperties = /* @__PURE__ */ new Map(), u2.elementStyles = [], u2.shadowRootOptions = { mode: "open" }, null == o2 || o2({ ReactiveElement: u2 }), (null !== (s2 = e2.reactiveElementVersions) && void 0 !== s2 ? s2 : e2.reactiveElementVersions = []).push("1.6.3");

  // node_modules/lit-html/lit-html.js
  var t2;
  var i3 = window;
  var s3 = i3.trustedTypes;
  var e3 = s3 ? s3.createPolicy("lit-html", { createHTML: (t5) => t5 }) : void 0;
  var o3 = "$lit$";
  var n3 = `lit$${(Math.random() + "").slice(9)}$`;
  var l3 = "?" + n3;
  var h3 = `<${l3}>`;
  var r4 = document;
  var u3 = () => r4.createComment("");
  var d3 = (t5) => null === t5 || "object" != typeof t5 && "function" != typeof t5;
  var c2 = Array.isArray;
  var v2 = (t5) => c2(t5) || "function" == typeof (null == t5 ? void 0 : t5[Symbol.iterator]);
  var a2 = "[ 	\n\f\r]";
  var f2 = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g;
  var _ = /-->/g;
  var m2 = />/g;
  var p2 = RegExp(`>|${a2}(?:([^\\s"'>=/]+)(${a2}*=${a2}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`, "g");
  var g2 = /'/g;
  var $ = /"/g;
  var y2 = /^(?:script|style|textarea|title)$/i;
  var w2 = (t5) => (i7, ...s5) => ({ _$litType$: t5, strings: i7, values: s5 });
  var x2 = w2(1);
  var b2 = w2(2);
  var T2 = Symbol.for("lit-noChange");
  var A2 = Symbol.for("lit-nothing");
  var E2 = /* @__PURE__ */ new WeakMap();
  var C2 = r4.createTreeWalker(r4, 129, null, false);
  function P(t5, i7) {
    if (!Array.isArray(t5) || !t5.hasOwnProperty("raw")) throw Error("invalid template strings array");
    return void 0 !== e3 ? e3.createHTML(i7) : i7;
  }
  var V = (t5, i7) => {
    const s5 = t5.length - 1, e8 = [];
    let l6, r5 = 2 === i7 ? "<svg>" : "", u4 = f2;
    for (let i8 = 0; i8 < s5; i8++) {
      const s6 = t5[i8];
      let d4, c3, v4 = -1, a3 = 0;
      for (; a3 < s6.length && (u4.lastIndex = a3, c3 = u4.exec(s6), null !== c3); ) a3 = u4.lastIndex, u4 === f2 ? "!--" === c3[1] ? u4 = _ : void 0 !== c3[1] ? u4 = m2 : void 0 !== c3[2] ? (y2.test(c3[2]) && (l6 = RegExp("</" + c3[2], "g")), u4 = p2) : void 0 !== c3[3] && (u4 = p2) : u4 === p2 ? ">" === c3[0] ? (u4 = null != l6 ? l6 : f2, v4 = -1) : void 0 === c3[1] ? v4 = -2 : (v4 = u4.lastIndex - c3[2].length, d4 = c3[1], u4 = void 0 === c3[3] ? p2 : '"' === c3[3] ? $ : g2) : u4 === $ || u4 === g2 ? u4 = p2 : u4 === _ || u4 === m2 ? u4 = f2 : (u4 = p2, l6 = void 0);
      const w3 = u4 === p2 && t5[i8 + 1].startsWith("/>") ? " " : "";
      r5 += u4 === f2 ? s6 + h3 : v4 >= 0 ? (e8.push(d4), s6.slice(0, v4) + o3 + s6.slice(v4) + n3 + w3) : s6 + n3 + (-2 === v4 ? (e8.push(void 0), i8) : w3);
    }
    return [P(t5, r5 + (t5[s5] || "<?>") + (2 === i7 ? "</svg>" : "")), e8];
  };
  var N2 = class _N {
    constructor({ strings: t5, _$litType$: i7 }, e8) {
      let h4;
      this.parts = [];
      let r5 = 0, d4 = 0;
      const c3 = t5.length - 1, v4 = this.parts, [a3, f3] = V(t5, i7);
      if (this.el = _N.createElement(a3, e8), C2.currentNode = this.el.content, 2 === i7) {
        const t6 = this.el.content, i8 = t6.firstChild;
        i8.remove(), t6.append(...i8.childNodes);
      }
      for (; null !== (h4 = C2.nextNode()) && v4.length < c3; ) {
        if (1 === h4.nodeType) {
          if (h4.hasAttributes()) {
            const t6 = [];
            for (const i8 of h4.getAttributeNames()) if (i8.endsWith(o3) || i8.startsWith(n3)) {
              const s5 = f3[d4++];
              if (t6.push(i8), void 0 !== s5) {
                const t7 = h4.getAttribute(s5.toLowerCase() + o3).split(n3), i9 = /([.?@])?(.*)/.exec(s5);
                v4.push({ type: 1, index: r5, name: i9[2], strings: t7, ctor: "." === i9[1] ? H2 : "?" === i9[1] ? L2 : "@" === i9[1] ? z2 : k2 });
              } else v4.push({ type: 6, index: r5 });
            }
            for (const i8 of t6) h4.removeAttribute(i8);
          }
          if (y2.test(h4.tagName)) {
            const t6 = h4.textContent.split(n3), i8 = t6.length - 1;
            if (i8 > 0) {
              h4.textContent = s3 ? s3.emptyScript : "";
              for (let s5 = 0; s5 < i8; s5++) h4.append(t6[s5], u3()), C2.nextNode(), v4.push({ type: 2, index: ++r5 });
              h4.append(t6[i8], u3());
            }
          }
        } else if (8 === h4.nodeType) if (h4.data === l3) v4.push({ type: 2, index: r5 });
        else {
          let t6 = -1;
          for (; -1 !== (t6 = h4.data.indexOf(n3, t6 + 1)); ) v4.push({ type: 7, index: r5 }), t6 += n3.length - 1;
        }
        r5++;
      }
    }
    static createElement(t5, i7) {
      const s5 = r4.createElement("template");
      return s5.innerHTML = t5, s5;
    }
  };
  function S3(t5, i7, s5 = t5, e8) {
    var o7, n7, l6, h4;
    if (i7 === T2) return i7;
    let r5 = void 0 !== e8 ? null === (o7 = s5._$Co) || void 0 === o7 ? void 0 : o7[e8] : s5._$Cl;
    const u4 = d3(i7) ? void 0 : i7._$litDirective$;
    return (null == r5 ? void 0 : r5.constructor) !== u4 && (null === (n7 = null == r5 ? void 0 : r5._$AO) || void 0 === n7 || n7.call(r5, false), void 0 === u4 ? r5 = void 0 : (r5 = new u4(t5), r5._$AT(t5, s5, e8)), void 0 !== e8 ? (null !== (l6 = (h4 = s5)._$Co) && void 0 !== l6 ? l6 : h4._$Co = [])[e8] = r5 : s5._$Cl = r5), void 0 !== r5 && (i7 = S3(t5, r5._$AS(t5, i7.values), r5, e8)), i7;
  }
  var M2 = class {
    constructor(t5, i7) {
      this._$AV = [], this._$AN = void 0, this._$AD = t5, this._$AM = i7;
    }
    get parentNode() {
      return this._$AM.parentNode;
    }
    get _$AU() {
      return this._$AM._$AU;
    }
    u(t5) {
      var i7;
      const { el: { content: s5 }, parts: e8 } = this._$AD, o7 = (null !== (i7 = null == t5 ? void 0 : t5.creationScope) && void 0 !== i7 ? i7 : r4).importNode(s5, true);
      C2.currentNode = o7;
      let n7 = C2.nextNode(), l6 = 0, h4 = 0, u4 = e8[0];
      for (; void 0 !== u4; ) {
        if (l6 === u4.index) {
          let i8;
          2 === u4.type ? i8 = new R3(n7, n7.nextSibling, this, t5) : 1 === u4.type ? i8 = new u4.ctor(n7, u4.name, u4.strings, this, t5) : 6 === u4.type && (i8 = new Z(n7, this, t5)), this._$AV.push(i8), u4 = e8[++h4];
        }
        l6 !== (null == u4 ? void 0 : u4.index) && (n7 = C2.nextNode(), l6++);
      }
      return C2.currentNode = r4, o7;
    }
    v(t5) {
      let i7 = 0;
      for (const s5 of this._$AV) void 0 !== s5 && (void 0 !== s5.strings ? (s5._$AI(t5, s5, i7), i7 += s5.strings.length - 2) : s5._$AI(t5[i7])), i7++;
    }
  };
  var R3 = class _R {
    constructor(t5, i7, s5, e8) {
      var o7;
      this.type = 2, this._$AH = A2, this._$AN = void 0, this._$AA = t5, this._$AB = i7, this._$AM = s5, this.options = e8, this._$Cp = null === (o7 = null == e8 ? void 0 : e8.isConnected) || void 0 === o7 || o7;
    }
    get _$AU() {
      var t5, i7;
      return null !== (i7 = null === (t5 = this._$AM) || void 0 === t5 ? void 0 : t5._$AU) && void 0 !== i7 ? i7 : this._$Cp;
    }
    get parentNode() {
      let t5 = this._$AA.parentNode;
      const i7 = this._$AM;
      return void 0 !== i7 && 11 === (null == t5 ? void 0 : t5.nodeType) && (t5 = i7.parentNode), t5;
    }
    get startNode() {
      return this._$AA;
    }
    get endNode() {
      return this._$AB;
    }
    _$AI(t5, i7 = this) {
      t5 = S3(this, t5, i7), d3(t5) ? t5 === A2 || null == t5 || "" === t5 ? (this._$AH !== A2 && this._$AR(), this._$AH = A2) : t5 !== this._$AH && t5 !== T2 && this._(t5) : void 0 !== t5._$litType$ ? this.g(t5) : void 0 !== t5.nodeType ? this.$(t5) : v2(t5) ? this.T(t5) : this._(t5);
    }
    k(t5) {
      return this._$AA.parentNode.insertBefore(t5, this._$AB);
    }
    $(t5) {
      this._$AH !== t5 && (this._$AR(), this._$AH = this.k(t5));
    }
    _(t5) {
      this._$AH !== A2 && d3(this._$AH) ? this._$AA.nextSibling.data = t5 : this.$(r4.createTextNode(t5)), this._$AH = t5;
    }
    g(t5) {
      var i7;
      const { values: s5, _$litType$: e8 } = t5, o7 = "number" == typeof e8 ? this._$AC(t5) : (void 0 === e8.el && (e8.el = N2.createElement(P(e8.h, e8.h[0]), this.options)), e8);
      if ((null === (i7 = this._$AH) || void 0 === i7 ? void 0 : i7._$AD) === o7) this._$AH.v(s5);
      else {
        const t6 = new M2(o7, this), i8 = t6.u(this.options);
        t6.v(s5), this.$(i8), this._$AH = t6;
      }
    }
    _$AC(t5) {
      let i7 = E2.get(t5.strings);
      return void 0 === i7 && E2.set(t5.strings, i7 = new N2(t5)), i7;
    }
    T(t5) {
      c2(this._$AH) || (this._$AH = [], this._$AR());
      const i7 = this._$AH;
      let s5, e8 = 0;
      for (const o7 of t5) e8 === i7.length ? i7.push(s5 = new _R(this.k(u3()), this.k(u3()), this, this.options)) : s5 = i7[e8], s5._$AI(o7), e8++;
      e8 < i7.length && (this._$AR(s5 && s5._$AB.nextSibling, e8), i7.length = e8);
    }
    _$AR(t5 = this._$AA.nextSibling, i7) {
      var s5;
      for (null === (s5 = this._$AP) || void 0 === s5 || s5.call(this, false, true, i7); t5 && t5 !== this._$AB; ) {
        const i8 = t5.nextSibling;
        t5.remove(), t5 = i8;
      }
    }
    setConnected(t5) {
      var i7;
      void 0 === this._$AM && (this._$Cp = t5, null === (i7 = this._$AP) || void 0 === i7 || i7.call(this, t5));
    }
  };
  var k2 = class {
    constructor(t5, i7, s5, e8, o7) {
      this.type = 1, this._$AH = A2, this._$AN = void 0, this.element = t5, this.name = i7, this._$AM = e8, this.options = o7, s5.length > 2 || "" !== s5[0] || "" !== s5[1] ? (this._$AH = Array(s5.length - 1).fill(new String()), this.strings = s5) : this._$AH = A2;
    }
    get tagName() {
      return this.element.tagName;
    }
    get _$AU() {
      return this._$AM._$AU;
    }
    _$AI(t5, i7 = this, s5, e8) {
      const o7 = this.strings;
      let n7 = false;
      if (void 0 === o7) t5 = S3(this, t5, i7, 0), n7 = !d3(t5) || t5 !== this._$AH && t5 !== T2, n7 && (this._$AH = t5);
      else {
        const e9 = t5;
        let l6, h4;
        for (t5 = o7[0], l6 = 0; l6 < o7.length - 1; l6++) h4 = S3(this, e9[s5 + l6], i7, l6), h4 === T2 && (h4 = this._$AH[l6]), n7 || (n7 = !d3(h4) || h4 !== this._$AH[l6]), h4 === A2 ? t5 = A2 : t5 !== A2 && (t5 += (null != h4 ? h4 : "") + o7[l6 + 1]), this._$AH[l6] = h4;
      }
      n7 && !e8 && this.j(t5);
    }
    j(t5) {
      t5 === A2 ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, null != t5 ? t5 : "");
    }
  };
  var H2 = class extends k2 {
    constructor() {
      super(...arguments), this.type = 3;
    }
    j(t5) {
      this.element[this.name] = t5 === A2 ? void 0 : t5;
    }
  };
  var I2 = s3 ? s3.emptyScript : "";
  var L2 = class extends k2 {
    constructor() {
      super(...arguments), this.type = 4;
    }
    j(t5) {
      t5 && t5 !== A2 ? this.element.setAttribute(this.name, I2) : this.element.removeAttribute(this.name);
    }
  };
  var z2 = class extends k2 {
    constructor(t5, i7, s5, e8, o7) {
      super(t5, i7, s5, e8, o7), this.type = 5;
    }
    _$AI(t5, i7 = this) {
      var s5;
      if ((t5 = null !== (s5 = S3(this, t5, i7, 0)) && void 0 !== s5 ? s5 : A2) === T2) return;
      const e8 = this._$AH, o7 = t5 === A2 && e8 !== A2 || t5.capture !== e8.capture || t5.once !== e8.once || t5.passive !== e8.passive, n7 = t5 !== A2 && (e8 === A2 || o7);
      o7 && this.element.removeEventListener(this.name, this, e8), n7 && this.element.addEventListener(this.name, this, t5), this._$AH = t5;
    }
    handleEvent(t5) {
      var i7, s5;
      "function" == typeof this._$AH ? this._$AH.call(null !== (s5 = null === (i7 = this.options) || void 0 === i7 ? void 0 : i7.host) && void 0 !== s5 ? s5 : this.element, t5) : this._$AH.handleEvent(t5);
    }
  };
  var Z = class {
    constructor(t5, i7, s5) {
      this.element = t5, this.type = 6, this._$AN = void 0, this._$AM = i7, this.options = s5;
    }
    get _$AU() {
      return this._$AM._$AU;
    }
    _$AI(t5) {
      S3(this, t5);
    }
  };
  var B2 = i3.litHtmlPolyfillSupport;
  null == B2 || B2(N2, R3), (null !== (t2 = i3.litHtmlVersions) && void 0 !== t2 ? t2 : i3.litHtmlVersions = []).push("2.8.0");
  var D2 = (t5, i7, s5) => {
    var e8, o7;
    const n7 = null !== (e8 = null == s5 ? void 0 : s5.renderBefore) && void 0 !== e8 ? e8 : i7;
    let l6 = n7._$litPart$;
    if (void 0 === l6) {
      const t6 = null !== (o7 = null == s5 ? void 0 : s5.renderBefore) && void 0 !== o7 ? o7 : null;
      n7._$litPart$ = l6 = new R3(i7.insertBefore(u3(), t6), t6, void 0, null != s5 ? s5 : {});
    }
    return l6._$AI(t5), l6;
  };

  // node_modules/lit-element/lit-element.js
  var l4;
  var o4;
  var s4 = class extends u2 {
    constructor() {
      super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
    }
    createRenderRoot() {
      var t5, e8;
      const i7 = super.createRenderRoot();
      return null !== (t5 = (e8 = this.renderOptions).renderBefore) && void 0 !== t5 || (e8.renderBefore = i7.firstChild), i7;
    }
    update(t5) {
      const i7 = this.render();
      this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(t5), this._$Do = D2(i7, this.renderRoot, this.renderOptions);
    }
    connectedCallback() {
      var t5;
      super.connectedCallback(), null === (t5 = this._$Do) || void 0 === t5 || t5.setConnected(true);
    }
    disconnectedCallback() {
      var t5;
      super.disconnectedCallback(), null === (t5 = this._$Do) || void 0 === t5 || t5.setConnected(false);
    }
    render() {
      return T2;
    }
  };
  s4.finalized = true, s4._$litElement$ = true, null === (l4 = globalThis.litElementHydrateSupport) || void 0 === l4 || l4.call(globalThis, { LitElement: s4 });
  var n4 = globalThis.litElementPolyfillSupport;
  null == n4 || n4({ LitElement: s4 });
  (null !== (o4 = globalThis.litElementVersions) && void 0 !== o4 ? o4 : globalThis.litElementVersions = []).push("3.3.3");

  // node_modules/@lit/reactive-element/decorators/custom-element.js
  var e4 = (e8) => (n7) => "function" == typeof n7 ? ((e9, n8) => (customElements.define(e9, n8), n8))(e8, n7) : ((e9, n8) => {
    const { kind: t5, elements: s5 } = n8;
    return { kind: t5, elements: s5, finisher(n9) {
      customElements.define(e9, n9);
    } };
  })(e8, n7);

  // node_modules/@lit/reactive-element/decorators/property.js
  var i4 = (i7, e8) => "method" === e8.kind && e8.descriptor && !("value" in e8.descriptor) ? { ...e8, finisher(n7) {
    n7.createProperty(e8.key, i7);
  } } : { kind: "field", key: Symbol(), placement: "own", descriptor: {}, originalKey: e8.key, initializer() {
    "function" == typeof e8.initializer && (this[e8.key] = e8.initializer.call(this));
  }, finisher(n7) {
    n7.createProperty(e8.key, i7);
  } };
  var e5 = (i7, e8, n7) => {
    e8.constructor.createProperty(n7, i7);
  };
  function n5(n7) {
    return (t5, o7) => void 0 !== o7 ? e5(n7, t5, o7) : i4(n7, t5);
  }

  // node_modules/@lit/reactive-element/decorators/state.js
  function t3(t5) {
    return n5({ ...t5, state: true });
  }

  // node_modules/@lit/reactive-element/decorators/base.js
  var o5 = ({ finisher: e8, descriptor: t5 }) => (o7, n7) => {
    var r5;
    if (void 0 === n7) {
      const n8 = null !== (r5 = o7.originalKey) && void 0 !== r5 ? r5 : o7.key, i7 = null != t5 ? { kind: "method", placement: "prototype", key: n8, descriptor: t5(o7.key) } : { ...o7, key: n8 };
      return null != e8 && (i7.finisher = function(t6) {
        e8(t6, n8);
      }), i7;
    }
    {
      const r6 = o7.constructor;
      void 0 !== t5 && Object.defineProperty(o7, n7, t5(n7)), null == e8 || e8(r6, n7);
    }
  };

  // node_modules/@lit/reactive-element/decorators/query.js
  function i5(i7, n7) {
    return o5({ descriptor: (o7) => {
      const t5 = { get() {
        var o8, n8;
        return null !== (n8 = null === (o8 = this.renderRoot) || void 0 === o8 ? void 0 : o8.querySelector(i7)) && void 0 !== n8 ? n8 : null;
      }, enumerable: true, configurable: true };
      if (n7) {
        const n8 = "symbol" == typeof o7 ? Symbol() : "__" + o7;
        t5.get = function() {
          var o8, t6;
          return void 0 === this[n8] && (this[n8] = null !== (t6 = null === (o8 = this.renderRoot) || void 0 === o8 ? void 0 : o8.querySelector(i7)) && void 0 !== t6 ? t6 : null), this[n8];
        };
      }
      return t5;
    } });
  }

  // node_modules/@lit/reactive-element/decorators/query-assigned-elements.js
  var n6;
  var e6 = null != (null === (n6 = window.HTMLSlotElement) || void 0 === n6 ? void 0 : n6.prototype.assignedElements) ? (o7, n7) => o7.assignedElements(n7) : (o7, n7) => o7.assignedNodes(n7).filter(((o8) => o8.nodeType === Node.ELEMENT_NODE));

  // node_modules/lit-html/directive.js
  var t4 = { ATTRIBUTE: 1, CHILD: 2, PROPERTY: 3, BOOLEAN_ATTRIBUTE: 4, EVENT: 5, ELEMENT: 6 };
  var e7 = (t5) => (...e8) => ({ _$litDirective$: t5, values: e8 });
  var i6 = class {
    constructor(t5) {
    }
    get _$AU() {
      return this._$AM._$AU;
    }
    _$AT(t5, e8, i7) {
      this._$Ct = t5, this._$AM = e8, this._$Ci = i7;
    }
    _$AS(t5, e8) {
      return this.update(t5, e8);
    }
    update(t5, e8) {
      return this.render(...e8);
    }
  };

  // node_modules/lit-html/directives/class-map.js
  var o6 = e7(class extends i6 {
    constructor(t5) {
      var i7;
      if (super(t5), t5.type !== t4.ATTRIBUTE || "class" !== t5.name || (null === (i7 = t5.strings) || void 0 === i7 ? void 0 : i7.length) > 2) throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.");
    }
    render(t5) {
      return " " + Object.keys(t5).filter(((i7) => t5[i7])).join(" ") + " ";
    }
    update(i7, [s5]) {
      var r5, o7;
      if (void 0 === this.it) {
        this.it = /* @__PURE__ */ new Set(), void 0 !== i7.strings && (this.nt = new Set(i7.strings.join(" ").split(/\s/).filter(((t5) => "" !== t5))));
        for (const t5 in s5) s5[t5] && !(null === (r5 = this.nt) || void 0 === r5 ? void 0 : r5.has(t5)) && this.it.add(t5);
        return this.render(s5);
      }
      const e8 = i7.element.classList;
      this.it.forEach(((t5) => {
        t5 in s5 || (e8.remove(t5), this.it.delete(t5));
      }));
      for (const t5 in s5) {
        const i8 = !!s5[t5];
        i8 === this.it.has(t5) || (null === (o7 = this.nt) || void 0 === o7 ? void 0 : o7.has(t5)) || (i8 ? (e8.add(t5), this.it.add(t5)) : (e8.remove(t5), this.it.delete(t5)));
      }
      return T2;
    }
  });

  // node_modules/weq8c/dist/ui.js
  var le = class {
    constructor(e8, t5 = A, i7 = Q) {
      this.audioCtx = e8, this.spec = t5, this.supportedFilterTypes = i7, this.filterbank = [], this.saturatorNode = null, this._saturationMode = "none", this._saturationThreshold = 1, this.debugAnalyser = null, this.input = e8.createGain(), this.output = e8.createGain(), this.debugAnalyser = e8.createAnalyser(), this.debugAnalyser.fftSize = 1024, this.output.connect(this.debugAnalyser), this.buildFilterChain(t5), this.emitter = C();
    }
    connect(e8) {
      this.output.connect(e8);
    }
    disconnect(e8) {
      this.output.disconnect(e8);
    }
    on(e8, t5) {
      return this.emitter.on(e8, t5);
    }
    get saturationMode() {
      return this._saturationMode;
    }
    get saturationThreshold() {
      return this._saturationThreshold;
    }
    get inputGain() {
      return this.input.gain.value;
    }
    set inputGain(e8) {
      this.input.gain.value = e8;
    }
    get outputGain() {
      return this.output.gain.value;
    }
    set outputGain(e8) {
      this.output.gain.value = e8;
    }
    setSaturationMode(e8, t5) {
      var s5;
      const i7 = (s5 = t5 == null ? void 0 : t5.threshold) != null ? s5 : 1;
      this._saturationMode = e8, this._saturationThreshold = i7, this.rebuildSaturatorConnection(), this.emitter.emit("saturationChanged", e8);
    }
    rebuildSaturatorConnection() {
      this.saturatorNode && (this.saturatorNode.disconnect(), this.saturatorNode = null);
      const e8 = this.getLastActiveSourceNode();
      try {
        e8.disconnect(this.output);
      } catch {
      }
      if (this._saturationMode === "none")
        e8.connect(this.output);
      else if (this._saturationMode === "limit") {
        const t5 = this.audioCtx.createDynamicsCompressor();
        t5.threshold.value = -0.1, t5.knee.value = 0, t5.ratio.value = 20, t5.attack.value = 3e-3, t5.release.value = 0.05, this.saturatorNode = t5, e8.connect(t5), t5.connect(this.output);
      } else {
        const t5 = this.audioCtx.createWaveShaper();
        t5.oversample = "4x";
        const i7 = 4096;
        this._saturationMode === "hard" ? t5.curve = z(i7, this._saturationThreshold) : this._saturationMode === "soft" ? t5.curve = I(i7, this._saturationThreshold) : this._saturationMode === "foldback" && (t5.curve = K(i7, this._saturationThreshold)), this.saturatorNode = t5, e8.connect(t5), t5.connect(this.output);
      }
    }
    getLastActiveSourceNode() {
      if (this.filterbank.length === 0)
        return this.input;
      const e8 = this.filterbank[this.filterbank.length - 1];
      return e8.filters[e8.filters.length - 1];
    }
    setFilterType(e8, t5) {
      var i7;
      if (t5 === "noop" && this.spec[e8].type !== "noop" && !this.spec[e8].bypass && this.disconnectFilter(e8), t5 === "noop" ? this.spec[e8].bypass = false : this.spec[e8].type === "noop" && (this.spec[e8].bypass = false, this.connectFilter(e8, t5)), this.spec[e8].type = t5, t5 !== "noop" && !this.spec[e8].bypass) {
        let s5 = (i7 = this.filterbank.find((n7) => n7.idx === e8)) == null ? void 0 : i7.filters;
        if (!s5)
          throw new Error("Assertion failed: No filters in filterbank");
        for (let n7 of s5)
          n7.type = H(t5);
        let r5 = T(t5);
        for (; s5.length > r5; ) {
          let n7 = s5.length - 1, a3 = s5[n7], l6 = s5[n7 - 1], u4 = this.getNextInChain(e8);
          a3.disconnect(), l6.disconnect(a3), l6.connect(u4), s5.splice(n7, 1);
        }
        for (; s5.length < r5; ) {
          let n7 = this.audioCtx.createBiquadFilter();
          n7.type = H(t5), n7.frequency.value = this.spec[e8].frequency, n7.Q.value = this.spec[e8].Q, n7.gain.value = this.spec[e8].gain;
          let a3 = s5[s5.length - 1], l6 = this.getNextInChain(e8);
          a3.disconnect(l6), a3.connect(n7), n7.connect(l6), s5.push(n7);
        }
      }
      this.emitter.emit("filtersChanged", this.spec);
    }
    toggleBypass(e8, t5) {
      t5 && !this.spec[e8].bypass && this.spec[e8].type !== "noop" ? this.disconnectFilter(e8) : !t5 && this.spec[e8].bypass && this.spec[e8].type !== "noop" && this.connectFilter(e8, this.spec[e8].type), this.spec[e8].bypass = t5, this.emitter.emit("filtersChanged", this.spec);
    }
    disconnectFilter(e8) {
      var r5;
      let t5 = (r5 = this.filterbank.find((n7) => n7.idx === e8)) == null ? void 0 : r5.filters;
      if (!t5)
        throw new Error(
          "Assertion failed: No filters in filterbank when disconnecting filter. Was it connected?"
        );
      let i7 = this.getPreviousInChain(e8), s5 = this.getNextInChain(e8);
      i7.disconnect(t5[0]), t5[t5.length - 1].disconnect(s5), i7.connect(s5), this.filterbank = this.filterbank.filter((n7) => n7.idx !== e8), this.rebuildSaturatorConnection();
    }
    connectFilter(e8, t5) {
      let i7 = Array.from({ length: T(t5) }, () => {
        let n7 = this.audioCtx.createBiquadFilter();
        return n7.type = H(t5), n7.frequency.value = this.spec[e8].frequency, n7.Q.value = this.spec[e8].Q, n7.gain.value = this.spec[e8].gain, n7;
      }), s5 = this.getPreviousInChain(e8), r5 = this.getNextInChain(e8);
      s5.disconnect(r5), s5.connect(i7[0]);
      for (let n7 = 0; n7 < i7.length - 1; n7++)
        i7[n7].connect(i7[n7 + 1]);
      i7[i7.length - 1].connect(r5), this.filterbank.push({ idx: e8, filters: i7 }), this.filterbank.sort((n7, a3) => n7.idx - a3.idx), this.rebuildSaturatorConnection();
    }
    setFilterFrequency(e8, t5) {
      this.spec[e8].frequency = t5;
      let i7 = this.filterbank.find((s5) => s5.idx === e8);
      if (i7)
        for (let s5 of i7.filters)
          s5.frequency.value = t5;
      this.emitter.emit("filtersChanged", this.spec);
    }
    setFilterQ(e8, t5) {
      this.spec[e8].Q = t5;
      let i7 = this.filterbank.find((s5) => s5.idx === e8);
      if (i7)
        for (let s5 of i7.filters)
          s5.Q.value = t5;
      this.emitter.emit("filtersChanged", this.spec);
    }
    setFilterGain(e8, t5) {
      this.spec[e8].gain = t5;
      let i7 = this.filterbank.find((s5) => s5.idx === e8);
      if (i7)
        for (let s5 of i7.filters)
          s5.gain.value = t5;
      this.emitter.emit("filtersChanged", this.spec);
    }
    getEqResponseAtFrequency(e8) {
      const t5 = new Float32Array([e8]), i7 = new Float32Array(1), s5 = new Float32Array(1);
      let r5 = 1, n7 = 0;
      for (let a3 = 0; a3 < this.spec.length; a3++) {
        if (this.spec[a3].type === "noop" || this.spec[a3].bypass)
          continue;
        const l6 = T(this.spec[a3].type);
        for (let u4 = 0; u4 < l6; u4++)
          this.getFrequencyResponse(
            a3,
            u4,
            t5,
            i7,
            s5
          ) && (r5 *= i7[0], n7 += s5[0]);
      }
      return {
        magnitudeDb: r5 > 0 ? 20 * Math.log10(r5) : -96,
        phaseDeg: n7 * 180 / Math.PI
      };
    }
    getFrequencyResponse(e8, t5, i7, s5, r5) {
      let n7 = this.filterbank.find((a3) => a3.idx === e8);
      return n7 ? (n7.filters[t5].getFrequencyResponse(
        i7,
        s5,
        r5
      ), true) : false;
    }
    getDebugStats() {
      const t5 = new Float32Array(512), i7 = this.audioCtx.sampleRate / 2, s5 = Math.log10(20), r5 = Math.log10(i7);
      for (let d4 = 0; d4 < 512; d4++) {
        const g3 = s5 + d4 / 511 * (r5 - s5);
        t5[d4] = Math.pow(10, g3);
      }
      const n7 = new Float32Array(512), a3 = new Float32Array(512);
      n7.fill(1), a3.fill(0);
      const l6 = new Float32Array(512), u4 = new Float32Array(512);
      let o7 = 0, c3 = 0;
      for (let d4 = 0; d4 < this.spec.length; d4++) {
        if (this.spec[d4].type === "noop" || this.spec[d4].bypass)
          continue;
        o7++;
        const g3 = T(this.spec[d4].type);
        c3 += g3;
        for (let q2 = 0; q2 < g3; q2++)
          if (this.getFrequencyResponse(d4, q2, t5, l6, u4))
            for (let $2 = 0; $2 < 512; $2++)
              n7[$2] *= l6[$2], a3[$2] += u4[$2];
      }
      let h4 = 0, w3 = 1 / 0, P2 = 0, M3 = 0, z3 = 0;
      for (let d4 = 0; d4 < 512; d4++) {
        const g3 = n7[d4];
        g3 > h4 && (h4 = g3, P2 = t5[d4]), g3 < w3 && (w3 = g3, M3 = t5[d4]);
        const q2 = Math.abs(a3[d4]);
        q2 > z3 && (z3 = q2);
      }
      const O = h4 > 0 ? 20 * Math.log10(h4) : -96, G = w3 > 0 ? 20 * Math.log10(w3) : -96, F2 = z3 * 180 / Math.PI;
      let N3 = -96, Q3 = 0, B3 = false;
      if (this.debugAnalyser) {
        const d4 = new Float32Array(this.debugAnalyser.fftSize);
        this.debugAnalyser.getFloatTimeDomainData(d4);
        let g3 = 0;
        for (let D3 = 0; D3 < d4.length; D3++) {
          const te = Math.abs(d4[D3]);
          te > g3 && (g3 = te);
        }
        g3 > 0 && (N3 = 20 * Math.log10(g3));
        const q2 = this._saturationMode === "none" ? 1 : this._saturationThreshold;
        B3 = g3 >= q2;
        const x3 = new Float32Array(this.debugAnalyser.frequencyBinCount);
        this.debugAnalyser.getFloatFrequencyData(x3);
        let $2 = -1 / 0, ee = 0;
        for (let D3 = 0; D3 < x3.length; D3++)
          x3[D3] > $2 && ($2 = x3[D3], ee = D3);
        Q3 = ee * this.audioCtx.sampleRate / this.debugAnalyser.fftSize;
      }
      return {
        curveMaxDb: O,
        curveMaxDbFreq: P2,
        curveMinDb: G,
        curveMinDbFreq: M3,
        curveMaxPhase: F2,
        activeBandsCount: o7,
        totalBiquadNodes: c3,
        audioMaxDb: N3,
        audioMaxDbFreq: Q3,
        isClipping: B3,
        version: le.version,
        inputGain: this.inputGain,
        outputGain: this.outputGain
      };
    }
    buildFilterChain(e8) {
      this.filterbank = [];
      for (let t5 = 0; t5 < e8.length; t5++) {
        let i7 = e8[t5];
        if (i7.type === "noop" || i7.bypass)
          continue;
        let s5 = Array.from(
          { length: T(i7.type) },
          () => {
            let r5 = this.audioCtx.createBiquadFilter();
            return r5.type = H(i7.type), r5.frequency.value = i7.frequency, r5.Q.value = i7.Q, r5.gain.value = i7.gain, r5;
          }
        );
        this.filterbank.push({ idx: t5, filters: s5 });
      }
      if (this.filterbank.length > 0)
        for (let t5 = 0; t5 < this.filterbank.length; t5++) {
          let { filters: i7 } = this.filterbank[t5];
          t5 === 0 ? this.input.connect(i7[0]) : this.filterbank[t5 - 1].filters[this.filterbank[t5 - 1].filters.length - 1].connect(i7[0]);
          for (let s5 = 0; s5 < i7.length - 1; s5++)
            i7[s5].connect(i7[s5 + 1]);
        }
      this.rebuildSaturatorConnection();
    }
    getPreviousInChain(e8) {
      let t5 = this.input, i7 = -1;
      for (let s5 of this.filterbank)
        s5.idx < e8 && s5.idx > i7 && (t5 = s5.filters[s5.filters.length - 1], i7 = s5.idx);
      return t5;
    }
    getNextInChain(e8) {
      let t5 = this.saturatorNode || this.output, i7 = this.spec.length;
      for (let s5 of this.filterbank)
        s5.idx > e8 && s5.idx < i7 && (t5 = s5.filters[0], i7 = s5.idx);
      return t5;
    }
  };
  var ue = le;
  ue.version = N.version;
  var be = class {
    constructor(t5, i7) {
      this.runtime = t5, this.canvas = i7, this.disposed = false, this.analyser = t5.audioCtx.createAnalyser(), this.analyser.fftSize = 8192, this.analyser.smoothingTimeConstant = 0.5, t5.connect(this.analyser), this.analysisData = new Uint8Array(this.analyser.frequencyBinCount);
      let s5 = Math.log10(t5.audioCtx.sampleRate / 2) - 1;
      this.canvas.width = this.canvas.offsetWidth * window.devicePixelRatio, this.canvas.height = this.canvas.offsetHeight * window.devicePixelRatio, this.analysisXs = this.calculateAnalysisXs(s5), this.resizeObserver = new ResizeObserver(() => {
        this.canvas.width = this.canvas.offsetWidth * window.devicePixelRatio, this.canvas.height = this.canvas.offsetHeight * window.devicePixelRatio, this.analysisXs = this.calculateAnalysisXs(s5);
      }), this.resizeObserver.observe(this.canvas);
    }
    calculateAnalysisXs(t5) {
      return Array.from(this.analysisData).map((i7, s5) => {
        let r5 = s5 / this.analysisData.length * (this.runtime.audioCtx.sampleRate / 2);
        return Math.floor((Math.log10(r5) - 1) / t5 * this.canvas.width);
      });
    }
    analyse() {
      let t5 = () => {
        this.disposed || (this.analyser.getByteFrequencyData(this.analysisData), this.draw(), requestAnimationFrame(t5));
      };
      requestAnimationFrame(t5);
    }
    draw() {
      let t5 = this.canvas.width, i7 = this.canvas.height, s5 = this.canvas.height / 255, r5 = this.canvas.getContext("2d");
      if (!r5)
        throw new Error("Could not get a canvas context!");
      r5.clearRect(0, 0, t5, i7);
      let n7 = new Path2D();
      n7.moveTo(0, i7);
      for (let a3 = 0; a3 < this.analysisData.length; a3++) {
        let l6 = Math.floor(i7 - this.analysisData[a3] * s5);
        n7.lineTo(this.analysisXs[a3], l6);
      }
      n7.lineTo(t5, i7), r5.fillStyle = "rgba(30, 30, 60, 0.7)", r5.fill(n7), r5.strokeStyle = "rgb(155, 155, 255)", r5.stroke(n7);
    }
    dispose() {
      this.disposed = true, this.analyser.disconnect(), this.resizeObserver.disconnect();
    }
  };
  var me = class {
    constructor(t5, i7) {
      this.runtime = t5, this.canvas = i7, this.canvas.width = this.canvas.offsetWidth * window.devicePixelRatio, this.canvas.height = this.canvas.offsetHeight * window.devicePixelRatio, this.frequencies = this.calculateFrequencies(), this.filterMagResponse = new Float32Array(this.frequencies.length), this.filterPhaseResponse = new Float32Array(this.frequencies.length), this.frequencyResponse = new Float32Array(this.frequencies.length), this.resizeObserver = new ResizeObserver(() => {
        this.canvas.width = this.canvas.offsetWidth * window.devicePixelRatio, this.canvas.height = this.canvas.offsetHeight * window.devicePixelRatio, this.frequencies = this.calculateFrequencies(), this.filterMagResponse = new Float32Array(this.frequencies.length), this.filterPhaseResponse = new Float32Array(this.frequencies.length), this.frequencyResponse = new Float32Array(this.frequencies.length), this.render();
      }), this.resizeObserver.observe(this.canvas);
    }
    dispose() {
      this.resizeObserver.disconnect();
    }
    render() {
      this.frequencyResponse.fill(1);
      for (let t5 = 0; t5 < this.runtime.spec.length; t5++)
        for (let i7 = 0; i7 < T(this.runtime.spec[t5].type); i7++)
          if (this.runtime.getFrequencyResponse(
            t5,
            i7,
            this.frequencies,
            this.filterMagResponse,
            this.filterPhaseResponse
          ))
            for (let r5 = 0; r5 < this.frequencyResponse.length; r5++)
              this.frequencyResponse[r5] *= this.filterMagResponse[r5];
      this.draw();
    }
    draw() {
      let t5 = this.canvas.getContext("2d"), i7 = this.canvas.width, s5 = this.canvas.height;
      if (!t5)
        throw new Error("Could not get a canvas context!");
      t5.clearRect(0, 0, i7, s5), t5.strokeStyle = "#ffffff", t5.lineWidth = 2, t5.beginPath();
      let r5 = 13, n7 = -r5;
      for (let a3 = 0; a3 < this.frequencyResponse.length; a3++) {
        let l6 = this.frequencyResponse[a3], u4 = 20 * Math.log10(l6), o7 = s5 - (u4 - n7) / (r5 - n7) * s5;
        a3 === 0 ? t5.moveTo(a3, o7) : t5.lineTo(a3, o7);
      }
      t5.stroke();
    }
    calculateFrequencies() {
      let t5 = new Float32Array(this.canvas.width), i7 = this.runtime.audioCtx.sampleRate / 2, s5 = 1, r5 = Math.log10(i7);
      for (let n7 = 0; n7 < this.canvas.width; n7++) {
        let a3 = s5 + n7 / this.canvas.width * (r5 - s5), l6 = Math.pow(10, a3);
        t5[n7] = l6;
      }
      return t5;
    }
  };
  var J = i2`
  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }

  :host {
    background-color: #111;
    color: white;
    --font-stack: "Inter", sans-serif;
    --font-size: 11px;
    --font-weight: 500;
    font-family: var(--font-stack);
    font-size: var(--font-size);
    font-weight: var(--font-weight);
  }
`;
  var V2 = [
    ["noop", "Add"],
    ["lowpass12", "LP12"],
    ["lowpass24", "LP24"],
    ["highpass12", "HP12"],
    ["highpass24", "HP24"],
    ["lowshelf12", "LS12"],
    ["lowshelf24", "LS24"],
    ["highshelf12", "HS12"],
    ["highshelf24", "HS24"],
    ["peaking12", "PK12"],
    ["peaking24", "PK24"],
    ["notch12", "NT12"],
    ["notch24", "NT24"]
  ];
  var ve = Object.defineProperty;
  var xe = Object.getOwnPropertyDescriptor;
  var L3 = (e8, t5, i7, s5) => {
    for (var r5 = s5 > 1 ? void 0 : s5 ? xe(t5, i7) : t5, n7 = e8.length - 1, a3; n7 >= 0; n7--)
      (a3 = e8[n7]) && (r5 = (s5 ? a3(t5, i7, r5) : a3(r5)) || r5);
    return s5 && r5 && ve(t5, i7, r5), r5;
  };
  var T3 = class extends s4 {
    constructor() {
      super(), this.onBandDragOver = (e8) => {
        this.index !== void 0 && (e8.preventDefault(), e8.dataTransfer && (e8.dataTransfer.dropEffect = "move"), this.dispatchEvent(
          new CustomEvent("band-drag-over", {
            detail: { index: this.index },
            bubbles: true,
            composed: true
          })
        ));
      }, this.onBandDragLeave = () => {
        this.index !== void 0 && this.dispatchEvent(
          new CustomEvent("band-drag-leave", {
            detail: { index: this.index },
            bubbles: true,
            composed: true
          })
        );
      }, this.onBandDrop = (e8) => {
        this.index !== void 0 && (e8.preventDefault(), this.dispatchEvent(
          new CustomEvent("band-drop", {
            detail: { index: this.index },
            bubbles: true,
            composed: true
          })
        ));
      }, this.frequencyInputFocused = false, this.dragStates = { frequency: null, gain: null, Q: null }, this.addEventListener(
        "click",
        () => this.dispatchEvent(
          new CustomEvent("select", { composed: true, bubbles: true })
        )
      ), this.addEventListener("dragover", this.onBandDragOver), this.addEventListener("dragleave", this.onBandDragLeave), this.addEventListener("drop", this.onBandDrop);
    }
    static addCustomStyles(e8) {
      const t5 = r2(e8);
      Array.isArray(this.styles) ? this.styles = [...this.styles, t5] : this.styles ? this.styles = [this.styles, t5] : this.styles = [t5], this.finalizeStyles && (this.elementStyles = this.finalizeStyles(this.styles));
    }
    render() {
      var n7, a3, l6, u4, o7, c3;
      if (!this.runtime || this.index === void 0)
        return;
      let e8 = this.runtime.spec[this.index];
      const t5 = e8.type === "noop";
      let i7 = V2.filter(
        (h4) => h4[0] !== "noop" && this.runtime.supportedFilterTypes.includes(h4[0])
      );
      const s5 = M(
        this.runtime.spec,
        this.index
      ), r5 = S(this.runtime.spec, this.index);
      return x2`
      <th>
        <div
          class=${o6({
        chip: true,
        disabled: t5,
        bypassed: e8.bypass
      })}
        >
          <div
            class=${o6({
        filterNumber: true,
        bypassed: e8.bypass
      })}
            draggable=${t5 ? "false" : "true"}
            @click=${() => {
        t5 ? this.setFilterType(r5) : this.toggleBypass();
      }}
            @contextmenu=${(h4) => {
        t5 || (h4.preventDefault(), h4.stopPropagation(), this.setFilterType("noop"));
      }}
            @dragstart=${(h4) => {
        if (t5) {
          h4.preventDefault();
          return;
        }
        h4.dataTransfer.effectAllowed = "move", this.dispatchEvent(new CustomEvent("band-drag-start", {
          detail: { index: this.index },
          bubbles: true,
          composed: true
        }));
      }}
            title=${t5 ? "Click to Add Band" : "Click to Toggle Bypass / Right-click to Remove | Drag to reorder"}
          >
            ${t5 ? x2`<span class="powerIcon" aria-hidden="true"
                  ><svg viewBox="0 -960 960 960" width="11" height="11" fill="currentColor"
                    ><path
                      d="M480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-84 31.5-156.5T197-763l56 56q-44 44-68.5 102T160-480q0 134 93 227t227 93q134 0 227-93t93-227q0-67-24.5-125T707-707l56-56q54 54 85.5 126.5T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm-40-360v-440h80v440h-80Z"
                    /></svg
                  ></span>` : s5}
          </div>
          <div class="chipType">
            ${t5 ? x2`<span
                  class="addBandLabel"
                  @click=${() => this.setFilterType(r5)}
                  title="Add ${(a3 = (n7 = V2.find((h4) => h4[0] === r5)) == null ? void 0 : n7[1]) != null ? a3 : r5}"
                  >${(u4 = (l6 = V2.find((h4) => h4[0] === "noop")) == null ? void 0 : l6[1]) != null ? u4 : "Add"}</span
                >` : x2`
                  <span
                    style="color: ${e8.bypass ? "#7d7d7d" : "white"}; font-family: var(--font-stack); font-size: var(--font-size); font-weight: var(--font-weight); pointer-events: none; text-align: center; white-space: nowrap;"
                  >
                    ${(c3 = (o7 = V2.find((h4) => h4[0] === e8.type)) == null ? void 0 : o7[1]) != null ? c3 : e8.type}
                  </span>
                  <select
                    class=${o6({
        filterTypeSelect: true,
        bypassed: e8.bypass
      })}
                    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; margin: 0; padding: 0;"
                    @change=${(h4) => this.setFilterType(
        h4.target.value
      )}
                    @click=${(h4) => h4.stopPropagation()}
                  >
                    ${i7.map(
        ([h4, w3]) => x2`<option value=${h4} ?selected=${e8.type === h4}>
                        ${j(
          w3,
          h4,
          r5
        )}
                      </option>`
      )}
                  </select>
                `}
          </div>
        </div>
      </th>
      <td>
        <input
          class=${o6({
        frequencyInput: true,
        numberInput: true,
        bypassed: e8.bypass
      })}
          type="number"
          step="0.1"
          lang="en_EN"
          .value=${R(e8.frequency, this.frequencyInputFocused)}
          ?disabled=${!L(e8.type)}
          @focus=${() => this.frequencyInputFocused = true}
          @blur=${() => {
        this.frequencyInputFocused = false, this.setFilterFrequency(i(e8.frequency, 10, this.nyquist));
      }}
          @input=${(h4) => this.setFilterFrequency(h4.target.valueAsNumber)}
          @pointerdown=${(h4) => this.startDraggingValue(h4, "frequency")}
          @pointerup=${(h4) => this.stopDraggingValue(h4, "frequency")}
          @pointermove=${(h4) => this.dragValue(h4, "frequency")}
        />
        <span
          class=${o6({
        frequencyUnit: true,
        disabled: !L(e8.type),
        bypassed: e8.bypass
      })}
          >${W(
        e8.frequency,
        this.frequencyInputFocused
      )}</span
        >
      </td>
      <td>
        ${E(e8.type) ? x2`
          <input
            class=${o6({
        gainInput: true,
        numberInput: true,
        bypassed: e8.bypass
      })}
            type="number"
            min="-15"
            max="15"
            step="0.1"
            lang="en_EN"
            .value=${e8.gain.toFixed(1)}
            @input=${(h4) => this.setFilterGain(h4.target.valueAsNumber)}
            @pointerdown=${(h4) => this.startDraggingValue(h4, "gain")}
            @pointerup=${(h4) => this.stopDraggingValue(h4, "gain")}
            @pointermove=${(h4) => this.dragValue(h4, "gain")}
          />
          <span
            class=${o6({
        gainUnit: true,
        bypassed: e8.bypass
      })}
            >dB</span
          >
        ` : x2`
          <span class="disabled bypassed" style="font-family: var(--font-stack); font-size: var(--font-size); font-weight: var(--font-weight); display: block; text-align: right; width: 26px; line-height: 20px; color: #7d7d7d; cursor: not-allowed; user-select: none;">--</span>
        `}
      </td>
      <td>
        ${x(e8.type) ? x2`
          <input
            class=${o6({
        qInput: true,
        numberInput: true,
        bypassed: e8.bypass
      })}
            type="number"
            min="0.1"
            max="18"
            step="0.1"
            .value=${e8.Q.toFixed(2)}
            @input=${(h4) => this.setFilterQ(h4.target.valueAsNumber)}
            @pointerdown=${(h4) => this.startDraggingValue(h4, "Q")}
            @pointerup=${(h4) => this.stopDraggingValue(h4, "Q")}
            @pointermove=${(h4) => this.dragValue(h4, "Q")}
          />
        ` : x2`
          <span class="disabled bypassed" style="font-family: var(--font-stack); font-size: var(--font-size); font-weight: var(--font-weight); display: block; text-align: right; width: 30px; line-height: 20px; color: #7d7d7d; cursor: not-allowed; user-select: none;">--</span>
        `}
      </td>
    `;
    }
    get nyquist() {
      var e8, t5;
      return ((t5 = (e8 = this.runtime) == null ? void 0 : e8.audioCtx.sampleRate) != null ? t5 : 48e3) / 2;
    }
    toggleBypass() {
      !this.runtime || this.index === void 0 || this.runtime.toggleBypass(
        this.index,
        !this.runtime.spec[this.index].bypass
      );
    }
    setFilterType(e8) {
      !this.runtime || this.index === void 0 || this.runtime.setFilterType(this.index, e8);
    }
    setFilterFrequency(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterFrequency(this.index, e8);
    }
    setFilterGain(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterGain(this.index, e8);
    }
    setFilterQ(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterQ(this.index, e8);
    }
    startDraggingValue(e8, t5) {
      !this.runtime || this.index === void 0 || (e8.target.setPointerCapture(e8.pointerId), this.dragStates = {
        ...this.dragStates,
        [t5]: {
          pointer: e8.pointerId,
          startY: e8.clientY,
          startValue: this.runtime.spec[this.index][t5]
        }
      });
    }
    stopDraggingValue(e8, t5) {
      var i7;
      !this.runtime || this.index === void 0 || ((i7 = this.dragStates[t5]) == null ? void 0 : i7.pointer) === e8.pointerId && (e8.target.releasePointerCapture(e8.pointerId), this.dragStates = { ...this.dragStates, [t5]: null });
    }
    dragValue(e8, t5) {
      if (!this.runtime || this.index === void 0)
        return;
      let i7 = this.dragStates[t5];
      if (i7 && i7.pointer === e8.pointerId) {
        let s5 = i7.startY, n7 = -(e8.clientY - s5), a3 = i(n7 / 150, -1, 1);
        if (t5 === "frequency") {
          let l6 = 10, u4 = this.runtime.audioCtx.sampleRate / 2, o7 = D(i7.startValue, l6, u4), c3 = B(o7 + a3, l6, u4);
          this.runtime.setFilterFrequency(this.index, c3);
        } else if (t5 === "gain") {
          let l6 = a3 * 15;
          this.runtime.setFilterGain(
            this.index,
            i(i7.startValue + l6, -15, 15)
          );
        } else if (t5 === "Q") {
          let l6 = 0.1, u4 = 18, o7 = D(i7.startValue, l6, u4), c3 = B(o7 + a3, l6, u4);
          this.runtime.setFilterQ(this.index, c3);
        }
        e8.target.blur();
      }
    }
  };
  T3.styles = [
    J,
    i2`
      :host {
        display: grid;
        grid-auto-flow: column;
        grid-template-columns: 60px 60px 50px 40px;
        align-items: center;
        gap: 4px;
        background-color: transparent;
        border-radius: 22px;
        transition: background-color 0.15s ease;
      }
      :host(.selected) {
        background-color: #373737;
      }
      input,
      select {
        padding: 0;
        border: 0;
      }
      input {
        border-bottom: 1px solid transparent;
        transition: border-color 0.15s ease;
      }
      input:focus,
      input:active {
        border-color: white;
      }
      .chip {
        display: inline-grid;
        grid-auto-flow: column;
        gap: 3px;
        height: 20px;
        padding-right: 6px;
        border-radius: 10px;
        background: #373737;
        transition: background-color 0.15s ease;
      }
      :host(.selected) .chip .filterNumber {
        background: #ffcc00;
      }
      .chip.disabled:hover {
        background: #444444;
      }
      :host(.drag-over) {
        background-color: #373737;
        outline: 1px solid #ffcc00;
        outline-offset: -2px;
        border-radius: 22px;
      }
      .filterNumber {
        cursor: pointer;
        width: 20px;
        height: 20px;
        border-radius: 10px;
        display: grid;
        place-content: center;
        background: white;
        font-weight: var(--font-weight);
        color: black;
        transition: background-color 0.15s ease;
      }
      .filterNumber[draggable="true"] {
        cursor: grab;
      }
      .filterNumber[draggable="true"]:active {
        cursor: grabbing;
      }
      .chip.disabled .filterNumber {
        background: transparent;
        color: #7d7d7d;
        border: 0.5px solid #444444;
        box-sizing: border-box;
      }
      .chip.disabled:hover .filterNumber {
        color: white;
        border-color: #5a5a5a;
      }
      .powerIcon {
        display: block;
        line-height: 0;
      }
      .powerIcon svg {
        display: block;
      }
      .chip.bypassed .filterNumber {
        background: #7d7d7d;
        color: black;
      }
      .filterTypeSelect {
        width: 30px;
        appearance: none;
        outline: none;
        background-color: transparent;
        color: white;
        cursor: pointer;
        text-align: center;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
      }
      .filterTypeSelect option {
        background-color: #202020;
        color: white;
      }
      .filterTypeSelect.bypassed {
        color: #7d7d7d;
      }
      .chipType {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 20px;
        box-sizing: border-box;
      }
      .addBandLabel {
        cursor: pointer;
        pointer-events: all;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
        color: #7d7d7d;
        text-align: center;
        white-space: nowrap;
        user-select: none;
      }
      .chip.disabled:hover .addBandLabel {
        color: white;
      }
      .frequencyInput {
        width: 28px;
      }
      .gainInput {
        width: 26px;
      }
      .qInput {
        width: 30px;
      }
      .numberInput {
        appearance: none;
        outline: none;
        background-color: transparent;
        color: white;
        text-align: right;
        -moz-appearance: textfield;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
        touch-action: none;
      }
      .numberInput:disabled,
      .disabled {
        color: #7d7d7d;
        pointer-events: none;
      }
      .bypassed {
        color: #7d7d7d;
      }
      .numberInput::-webkit-inner-spin-button,
      .numberInput::-webkit-outer-spin-button {
        -webkit-appearance: none !important;
        margin: 0 !important;
      }
    `
  ];
  L3([
    n5({ attribute: false })
  ], T3.prototype, "runtime", 2);
  L3([
    n5()
  ], T3.prototype, "index", 2);
  L3([
    t3()
  ], T3.prototype, "frequencyInputFocused", 2);
  L3([
    t3()
  ], T3.prototype, "dragStates", 2);
  T3 = L3([
    e4("weq8-ui-filter-row")
  ], T3);
  var we = Object.defineProperty;
  var Fe = Object.getOwnPropertyDescriptor;
  var A3 = (e8, t5, i7, s5) => {
    for (var r5 = s5 > 1 ? void 0 : s5 ? Fe(t5, i7) : t5, n7 = e8.length - 1, a3; n7 >= 0; n7--)
      (a3 = e8[n7]) && (r5 = (s5 ? a3(t5, i7, r5) : a3(r5)) || r5);
    return s5 && r5 && we(t5, i7, r5), r5;
  };
  var k3 = class extends s4 {
    constructor() {
      super(...arguments), this.x = 0, this.y = 0, this.frequencyInputFocused = false, this.dragStates = { frequency: null, gain: null, Q: null }, this.posOnDragStart = null;
    }
    static addCustomStyles(e8) {
      const t5 = r2(e8);
      Array.isArray(this.styles) ? this.styles = [...this.styles, t5] : this.styles ? this.styles = [this.styles, t5] : this.styles = [t5], this.finalizeStyles && (this.elementStyles = this.finalizeStyles(this.styles));
    }
    render() {
      var n7, a3, l6, u4;
      if (!this.runtime || this.index === void 0)
        return;
      let e8 = V2.filter(
        (o7) => this.runtime.supportedFilterTypes.includes(o7[0])
      ), t5 = this.runtime.spec[this.index];
      const i7 = S(this.runtime.spec, this.index);
      let s5 = ((a3 = (n7 = this.posOnDragStart) == null ? void 0 : n7.x) != null ? a3 : this.x) - 100, r5 = ((u4 = (l6 = this.posOnDragStart) == null ? void 0 : l6.y) != null ? u4 : this.y) + 20;
      return console.log("hi", s5, r5), x2`
      <div class="root" style="transform: translate(${s5}px, ${r5}px);">
        <div>
          <div
            class=${o6({
        chip: true,
        disabled: !L(t5.type),
        bypassed: t5.bypass
      })}
          >
            <select
              class=${o6({
        filterTypeSelect: true,
        bypassed: t5.bypass
      })}
              @change=${(o7) => this.setFilterType(o7.target.value)}
            >
              ${e8.map(
        ([o7, c3]) => x2`<option value=${o7} ?selected=${t5.type === o7}>
                    ${j(c3, o7, i7)}
                  </option>`
      )}
            </select>
          </div>
        </div>
        <div>
          <input
            class=${o6({
        frequencyInput: true,
        numberInput: true,
        bypassed: t5.bypass
      })}
            type="number"
            step="0.1"
            lang="en_EN"
            .value=${R(
        t5.frequency,
        this.frequencyInputFocused
      )}
            ?disabled=${!L(t5.type)}
            @focus=${() => this.frequencyInputFocused = true}
            @blur=${() => {
        this.frequencyInputFocused = false, this.setFilterFrequency(i(t5.frequency, 10, this.nyquist));
      }}
            @input=${(o7) => this.setFilterFrequency(o7.target.valueAsNumber)}
            @pointerdown=${(o7) => this.startDraggingValue(o7, "frequency")}
            @pointerup=${(o7) => this.stopDraggingValue(o7, "frequency")}
            @pointermove=${(o7) => this.dragValue(o7, "frequency")}
          />
          <span
            class=${o6({
        frequencyUnit: true,
        disabled: !L(t5.type),
        bypassed: t5.bypass
      })}
            >${W(
        t5.frequency,
        this.frequencyInputFocused
      )}</span
          >
        </div>
        <div>
          <input
            class=${o6({
        gainInput: true,
        numberInput: true,
        bypassed: t5.bypass
      })}
            type="number"
            min="-15"
            max="15"
            step="0.1"
            lang="en_EN"
            .value=${t5.gain.toFixed(1)}
            ?disabled=${!E(t5.type)}
            @input=${(o7) => this.setFilterGain(o7.target.valueAsNumber)}
            @pointerdown=${(o7) => this.startDraggingValue(o7, "gain")}
            @pointerup=${(o7) => this.stopDraggingValue(o7, "gain")}
            @pointermove=${(o7) => this.dragValue(o7, "gain")}
          />
          <span
            class=${o6({
        gainUnit: true,
        disabled: !E(t5.type),
        bypassed: t5.bypass
      })}
            >dB</span
          >
        </div>
        <div>
          <input
            class=${o6({
        qInput: true,
        numberInput: true,
        bypassed: t5.bypass
      })}
            type="number"
            min="0.1"
            max="18"
            step="0.1"
            .value=${t5.Q.toFixed(2)}
            ?disabled=${!x(t5.type)}
            @input=${(o7) => this.setFilterQ(o7.target.valueAsNumber)}
            @pointerdown=${(o7) => this.startDraggingValue(o7, "Q")}
            @pointerup=${(o7) => this.stopDraggingValue(o7, "Q")}
            @pointermove=${(o7) => this.dragValue(o7, "Q")}
          />
        </div>
      </div>
    `;
    }
    get nyquist() {
      var e8, t5;
      return ((t5 = (e8 = this.runtime) == null ? void 0 : e8.audioCtx.sampleRate) != null ? t5 : 48e3) / 2;
    }
    setFilterType(e8) {
      !this.runtime || this.index === void 0 || this.runtime.setFilterType(this.index, e8);
    }
    setFilterFrequency(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterFrequency(this.index, e8);
    }
    setFilterGain(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterGain(this.index, e8);
    }
    setFilterQ(e8) {
      !this.runtime || this.index === void 0 || isNaN(e8) || this.runtime.setFilterQ(this.index, e8);
    }
    startDraggingValue(e8, t5) {
      !this.runtime || this.index === void 0 || (e8.target.setPointerCapture(e8.pointerId), this.dragStates = {
        ...this.dragStates,
        [t5]: {
          pointer: e8.pointerId,
          startY: e8.clientY,
          startValue: this.runtime.spec[this.index][t5]
        }
      }, this.posOnDragStart = { x: this.x, y: this.y });
    }
    stopDraggingValue(e8, t5) {
      var i7;
      !this.runtime || this.index === void 0 || (((i7 = this.dragStates[t5]) == null ? void 0 : i7.pointer) === e8.pointerId && (e8.target.releasePointerCapture(e8.pointerId), this.dragStates = { ...this.dragStates, [t5]: null }), this.dragStates.frequency === null && this.dragStates.gain === null && this.dragStates.Q === null && (this.posOnDragStart = null));
    }
    dragValue(e8, t5) {
      if (!this.runtime || this.index === void 0)
        return;
      let i7 = this.dragStates[t5];
      if (i7 && i7.pointer === e8.pointerId) {
        let s5 = i7.startY, n7 = -(e8.clientY - s5), a3 = i(n7 / 150, -1, 1);
        if (t5 === "frequency") {
          let l6 = 10, u4 = this.runtime.audioCtx.sampleRate / 2, o7 = D(i7.startValue, l6, u4), c3 = B(o7 + a3, l6, u4);
          this.runtime.setFilterFrequency(this.index, c3);
        } else if (t5 === "gain") {
          let l6 = a3 * 15;
          this.runtime.setFilterGain(
            this.index,
            i(i7.startValue + l6, -15, 15)
          );
        } else if (t5 === "Q") {
          let l6 = 0.1, u4 = 18, o7 = D(i7.startValue, l6, u4), c3 = B(o7 + a3, l6, u4);
          this.runtime.setFilterQ(this.index, c3);
        }
        e8.target.blur();
      }
    }
  };
  k3.styles = [
    J,
    i2`
      .root {
        position: absolute;
        display: grid;
        grid-auto-flow: column;
        width: 210px;
        grid-template-columns: 60px 60px 50px 40px;
        align-items: center;
        gap: 4px;
        background-color: black;
        border-radius: 22px;
      }
      input,
      select {
        padding: 0;
        border: 0;
      }
      input {
        border-bottom: 1px solid transparent;
        transition: border-color 0.15s ease;
      }
      input:focus,
      input:active {
        border-color: white;
      }
      .chip {
        display: inline-grid;
        grid-auto-flow: column;
        gap: 3px;
        height: 20px;
        padding-right: 6px;
        border-radius: 10px;
        background: #373737;
        transition: background-color 0.15s ease;
      }
      .chip.disabled:hover {
        background: #444444;
      }
      .filterTypeSelect {
        width: 30px;
        appearance: none;
        outline: none;
        background-color: transparent;
        color: white;
        cursor: pointer;
        text-align: center;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
      }
      .filterTypeSelect option {
        background-color: #202020;
        color: white;
      }
      .filterTypeSelect.bypassed {
        color: #7d7d7d;
      }
      .chip.disabled .filterTypeSelect {
        pointer-events: all;
      }
      .frequencyInput {
        width: 28px;
      }
      .gainInput {
        width: 26px;
      }
      .qInput {
        width: 30px;
      }
      .numberInput {
        appearance: none;
        outline: none;
        background-color: transparent;
        color: white;
        text-align: right;
        -moz-appearance: textfield;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
        touch-action: none;
      }
      .numberInput:disabled,
      .disabled {
        color: #7d7d7d;
        pointer-events: none;
      }
      .bypassed {
        color: #7d7d7d;
      }
      .numberInput::-webkit-inner-spin-button,
      .numberInput::-webkit-outer-spin-button {
        -webkit-appearance: none !important;
        margin: 0 !important;
      }
    `
  ];
  A3([
    n5({ attribute: false })
  ], k3.prototype, "runtime", 2);
  A3([
    n5()
  ], k3.prototype, "index", 2);
  A3([
    n5()
  ], k3.prototype, "x", 2);
  A3([
    n5()
  ], k3.prototype, "y", 2);
  A3([
    t3()
  ], k3.prototype, "frequencyInputFocused", 2);
  A3([
    t3()
  ], k3.prototype, "dragStates", 2);
  A3([
    t3()
  ], k3.prototype, "posOnDragStart", 2);
  k3 = A3([
    e4("weq8-ui-filter-hud")
  ], k3);
  var qe = Object.defineProperty;
  var $e = Object.getOwnPropertyDescriptor;
  var v3 = (e8, t5, i7, s5) => {
    for (var r5 = s5 > 1 ? void 0 : s5 ? $e(t5, i7) : t5, n7 = e8.length - 1, a3; n7 >= 0; n7--)
      (a3 = e8[n7]) && (r5 = (s5 ? a3(t5, i7, r5) : a3(r5)) || r5);
    return s5 && r5 && qe(t5, i7, r5), r5;
  };
  var se = -13;
  var Ce = 13;
  var b3 = class extends s4 {
    constructor() {
      super(), this.onDocumentPointerDown = (e8) => {
        if (!this.curveContextMenu)
          return;
        const t5 = this.renderRoot.querySelector(".eq-context-menu");
        t5 && e8.composedPath().includes(t5) || (this.curveContextMenu = null);
      }, this.view = "allBands", this.gridXs = [], this.dragStates = {}, this.selectedFilterIdx = -1, this.dragSourceIdx = -1, this.dragOverIdx = -1, this.curveProbe = null, this.curveProbePointerId = null, this.curveContextMenu = null, this.onHostContextMenu = (e8) => {
        const t5 = e8.composedPath();
        if (this.isInsideVisualisation(t5) || this.isActiveBandNumberContextMenu(t5))
          return;
        e8.preventDefault(), e8.stopPropagation();
        const i7 = this.getBoundingClientRect(), s5 = 148, r5 = 32;
        this.curveContextMenu = {
          x: i(e8.clientX - i7.left, 4, Math.max(4, i7.width - s5 - 4)),
          y: i(e8.clientY - i7.top, 4, Math.max(4, i7.height - r5 - 4))
        };
      }, this.onVisualisationContextMenu = (e8) => {
        e8.target.closest(".filter-handle-positioner") || (e8.preventDefault(), e8.stopPropagation());
      }, this.onVisualisationPointerDown = (e8) => {
        e8.button !== 2 || !this.runtime || e8.target.closest(".filter-handle-positioner") || (this.curveContextMenu = null, e8.preventDefault(), e8.currentTarget.setPointerCapture(e8.pointerId), this.curveProbePointerId = e8.pointerId, this.updateCurveProbeFromPointer(e8));
      }, this.onVisualisationPointerMove = (e8) => {
        this.curveProbePointerId === e8.pointerId && this.updateCurveProbeFromPointer(e8);
      }, this.onVisualisationPointerUp = (e8) => {
        if (this.curveProbePointerId !== e8.pointerId)
          return;
        const t5 = e8.currentTarget;
        t5.hasPointerCapture(e8.pointerId) && t5.releasePointerCapture(e8.pointerId), this.curveProbePointerId = null, this.curveProbe = null;
      }, this.addEventListener("click", (e8) => {
        e8.composedPath()[0] === this && (this.selectedFilterIdx = -1);
      }), this.addEventListener("contextmenu", this.onHostContextMenu);
    }
    static addCustomStyles(e8) {
      const t5 = r2(e8);
      Array.isArray(this.styles) ? this.styles = [...this.styles, t5] : this.styles ? this.styles = [this.styles, t5] : this.styles = [t5], this.finalizeStyles && (this.elementStyles = this.finalizeStyles(this.styles));
    }
    connectedCallback() {
      super.connectedCallback(), document.addEventListener("pointerdown", this.onDocumentPointerDown, true);
    }
    disconnectedCallback() {
      document.removeEventListener("pointerdown", this.onDocumentPointerDown, true), super.disconnectedCallback();
    }
    updated(e8) {
      var t5, i7;
      if (e8.has("runtime") && ((t5 = this.analyser) == null || t5.dispose(), (i7 = this.frequencyResponse) == null || i7.dispose(), this.runtime && this.analyserCanvas && this.frequencyResponseCanvas)) {
        this.analyser = new be(this.runtime, this.analyserCanvas), this.analyser.analyse(), this.frequencyResponse = new me(
          this.runtime,
          this.frequencyResponseCanvas
        ), this.frequencyResponse.render();
        let s5 = [], r5 = this.runtime.audioCtx.sampleRate / 2, n7 = Math.floor(Math.log10(r5));
        for (let a3 = 0; a3 < n7; a3++) {
          let l6 = Math.pow(10, a3 + 1);
          for (let u4 = 1; u4 < 10; u4++) {
            let o7 = l6 * u4;
            if (o7 > r5)
              break;
            s5.push(
              (Math.log10(o7) - 1) / (Math.log10(r5) - 1) * 100
            );
          }
        }
        this.gridXs = s5, this.runtime.on("filtersChanged", () => {
          var a3, l6, u4;
          (a3 = this.frequencyResponse) == null || a3.render(), this.curveProbe && this.refreshCurveProbeAtFrequency(this.curveProbe.frequency), this.requestUpdate();
          for (let o7 of Array.from(
            (u4 = (l6 = this.shadowRoot) == null ? void 0 : l6.querySelectorAll("weq8-ui-filter-row")) != null ? u4 : []
          ))
            o7.requestUpdate();
        });
      }
      e8.has("view") && this.requestUpdate();
    }
    render() {
      var e8;
      return x2`
      ${this.view === "allBands" ? this.renderTable() : null}
      <div
        class="visualisation"
        @wheel=${(t5) => t5.preventDefault()}
        @contextmenu=${this.onVisualisationContextMenu}
        @pointerdown=${this.onVisualisationPointerDown}
        @pointermove=${this.onVisualisationPointerMove}
        @pointerup=${this.onVisualisationPointerUp}
        @pointercancel=${this.onVisualisationPointerUp}
      >
        <svg
          viewBox="0 0 100 10"
          preserveAspectRatio="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          ${this.gridXs.map(this.renderGridX)}
          ${[12, 6, 0, -6, -12].map(this.renderGridY)}
        </svg>
        <canvas class="analyser"></canvas>
        <canvas
          class="frequencyResponse"
          @click=${() => this.selectedFilterIdx = -1}
        ></canvas>
        <div class="curve-probe-layer">
          ${this.curveProbe ? this.renderCurveProbe() : null}
        </div>
        ${(e8 = this.runtime) == null ? void 0 : e8.spec.map(
        (t5, i7) => t5.type === "noop" ? void 0 : this.renderFilterHandle(t5, i7)
      )}
        ${this.view === "hud" && this.selectedFilterIdx !== -1 ? this.renderFilterHUD() : null}
      </div>
      ${this.curveContextMenu ? this.renderEqContextMenu() : null}
    `;
    }
    renderTable() {
      return x2` <table class="filters"
      @band-drag-start=${(e8) => {
        this.dragSourceIdx = e8.detail.index;
      }}
      @band-drag-over=${(e8) => {
        this.dragOverIdx = e8.detail.index;
      }}
      @band-drag-leave=${(e8) => {
        this.dragOverIdx === e8.detail.index && (this.dragOverIdx = -1);
      }}
      @band-drop=${(e8) => {
        const t5 = e8.detail.index;
        this.dragSourceIdx !== -1 && t5 !== this.dragSourceIdx && this.swapBands(this.dragSourceIdx, t5), this.dragSourceIdx = -1, this.dragOverIdx = -1;
      }}
      @dragend=${() => {
        this.dragSourceIdx = -1, this.dragOverIdx = -1;
      }}
    >
      <thead>
        <tr>
          <th class="headerFilter">Filter</th>
          <th>Freq</th>
          <th>Gain</th>
          <th>Q</th>
        </tr>
      </thead>
      <tbody>
        ${Array.from({ length: 8 }).map(
        (e8, t5) => x2`<weq8-ui-filter-row
              class="${o6({ selected: this.selectedFilterIdx === t5, "drag-over": this.dragOverIdx === t5 && this.dragSourceIdx !== t5 })}"
              .runtime=${this.runtime}
              .index=${t5}
              @select=${(i7) => {
          var s5;
          this.selectedFilterIdx = ((s5 = this.runtime) == null ? void 0 : s5.spec[t5].type) === "noop" ? -1 : t5, i7.stopPropagation();
        }}
            />`
      )}
      </tbody>
    </table>`;
    }
    renderFilterHUD() {
      var s5;
      if (!this.runtime)
        return x2``;
      let e8 = (s5 = this.runtime) == null ? void 0 : s5.spec[this.selectedFilterIdx], [t5, i7] = this.getFilterPositionInVisualisation(e8);
      return x2`<weq8-ui-filter-hud
      .runtime=${this.runtime}
      .index=${this.selectedFilterIdx}
      .x=${t5}
      .y=${i7}
    />`;
    }
    swapBands(e8, t5) {
      if (!this.runtime)
        return;
      const i7 = { ...this.runtime.spec[e8] }, s5 = { ...this.runtime.spec[t5] };
      for (const [r5, n7] of [[i7, t5], [s5, e8]])
        this.runtime.setFilterType(n7, r5.type), this.runtime.setFilterFrequency(n7, r5.frequency), this.runtime.setFilterGain(n7, r5.gain), this.runtime.setFilterQ(n7, r5.Q), r5.bypass !== this.runtime.spec[n7].bypass && this.runtime.toggleBypass(n7, r5.bypass);
    }
    renderEqContextMenu() {
      const e8 = this.curveContextMenu;
      return x2`
      <div
        class="eq-context-menu"
        style="left: ${e8.x}px; top: ${e8.y}px;"
        @contextmenu=${(t5) => t5.preventDefault()}
      >
        <div class="eq-context-menu-item">
          <strong>WEQ8C</strong> v${ue.version}
        </div>
      </div>
    `;
    }
    isInsideVisualisation(e8) {
      const t5 = this.renderRoot.querySelector(".visualisation");
      return t5 ? e8.includes(t5) : false;
    }
    isActiveBandNumberContextMenu(e8) {
      for (const t5 of e8)
        if (t5 instanceof HTMLElement && t5.classList.contains("filterNumber") && t5.getAttribute("draggable") === "true")
          return true;
      return false;
    }
    getProbeLayout(e8) {
      var B3, d4, g3, q2;
      const t5 = (d4 = (B3 = this.frequencyResponseCanvas) == null ? void 0 : B3.offsetWidth) != null ? d4 : 0, i7 = (q2 = (g3 = this.frequencyResponseCanvas) == null ? void 0 : g3.offsetHeight) != null ? q2 : 0, s5 = 8, a3 = 4 + 12, l6 = 118, u4 = 58, o7 = 0.45, c3 = i(e8.xPercent, o7, 100 - o7), h4 = i(e8.curveYPercent, o7, 100 - o7), w3 = e8.xPercent / 100 * t5, P2 = e8.curveYPercent / 100 * i7, M3 = P2 - a3 - u4 >= s5, z3 = P2 + a3 + u4 <= i7 - s5, O = w3 + a3 + l6 <= t5 - s5, G = w3 - a3 - l6 >= s5;
      let F2;
      if (M3 || z3) {
        const x3 = P2 - s5, $2 = i7 - s5 - P2;
        M3 && z3 ? F2 = x3 >= $2 ? "above" : "below" : F2 = M3 ? "above" : "below";
      } else
        O || G ? F2 = O && (!G || w3 < t5 / 2) ? "right" : "left" : F2 = P2 < i7 / 2 ? "below" : "above";
      let N3 = w3;
      if (F2 === "above" || F2 === "below") {
        const x3 = l6 / 2;
        N3 = i(N3, s5 + x3, t5 - s5 - x3);
      }
      let Q3 = P2;
      if (F2 === "left" || F2 === "right") {
        const x3 = u4 / 2;
        Q3 = i(Q3, s5 + x3, i7 - s5 - x3);
      }
      return {
        markerX: c3,
        markerY: h4,
        anchorLeft: `${N3}px`,
        anchorTop: `${Q3}px`,
        placement: F2
      };
    }
    renderCurveProbe() {
      const e8 = this.curveProbe, t5 = this.getProbeLayout(e8), i7 = e8.fromTop ? 0 : 100, s5 = e8.magnitudeDb >= 0 ? "+" : "";
      return x2`
      <svg
        class="curve-probe-overlay"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        <line
          class="curve-probe-line"
          x1=${t5.markerX}
          y1=${i7}
          x2=${t5.markerX}
          y2=${t5.markerY}
        />
      </svg>
      <div
        class="curve-probe-marker"
        style="left: ${t5.markerX}%; top: ${t5.markerY}%;"
      ></div>
      <div
        class="curve-probe-anchor"
        style="left: ${t5.anchorLeft}; top: ${t5.anchorTop};"
      >
        <div class="curve-probe-stats placement-${t5.placement}">
        <div class="probe-row">
          <span class="probe-label">Freq</span>
          <span class="probe-value"
            >${R(e8.frequency)}
            ${W(e8.frequency)}</span
          >
        </div>
        <div class="probe-row">
          <span class="probe-label">Gain</span>
          <span class="probe-value probe-db"
            >${s5}${e8.magnitudeDb.toFixed(2)} dB</span
          >
        </div>
        <div class="probe-row">
          <span class="probe-label">Phase</span>
          <span class="probe-value" style="color: #7d7d7d;"
            >${e8.phaseDeg.toFixed(1)}°</span
          >
        </div>
        </div>
      </div>
    `;
    }
    getVisualisationBounds() {
      var e8, t5;
      return (t5 = (e8 = this.frequencyResponseCanvas) == null ? void 0 : e8.getBoundingClientRect()) != null ? t5 : {
        left: 0,
        top: 0,
        width: 0,
        height: 0
      };
    }
    refreshCurveProbeAtFrequency(e8) {
      if (!this.runtime || this.getVisualisationBounds().width <= 0)
        return;
      const i7 = this.runtime.audioCtx.sampleRate / 2, s5 = D(e8, 10, i7) * 100, { magnitudeDb: r5, phaseDeg: n7 } = this.runtime.getEqResponseAtFrequency(e8), a3 = (r5 - se) / (Ce - se), l6 = i((1 - a3) * 100, 0, 100);
      this.curveProbe = {
        xPercent: s5,
        curveYPercent: l6,
        fromTop: r5 < 0,
        frequency: e8,
        magnitudeDb: r5,
        phaseDeg: n7
      };
    }
    updateCurveProbeFromPointer(e8) {
      if (!this.runtime)
        return;
      const t5 = this.getVisualisationBounds();
      if (t5.width <= 0 || t5.height <= 0)
        return;
      const i7 = i((e8.clientX - t5.left) / t5.width, 0, 1), s5 = B(i7, 10, this.runtime.audioCtx.sampleRate / 2);
      this.refreshCurveProbeAtFrequency(s5);
    }
    renderGridX(e8) {
      return b2`<line
      class="grid-x"
      x1=${e8}
      y1="0"
      x2=${e8}
      y2="10"
    />`;
    }
    renderGridY(e8) {
      let i7 = (e8 + 15) / 30 * 10;
      return b2`<line
      class="grid-y"
      x1="0"
      y1=${i7}
      x2="100"
      y2=${i7}
    />`;
    }
    renderFilterHandle(e8, t5) {
      var r5;
      if (!this.runtime)
        return;
      let [i7, s5] = this.getFilterPositionInVisualisation(e8);
      return x2`<div
      class="filter-handle-positioner"
      style="transform: translate(${i7}px,${s5}px)"
      @pointerdown=${(n7) => this.startDraggingFilterHandle(n7, t5)}
      @pointerup=${(n7) => this.stopDraggingFilterHandle(n7, t5)}
      @pointermove=${(n7) => this.dragFilterHandle(n7, t5)}
      @wheel=${(n7) => this.onWheelFilterHandle(n7, t5)}
    >
      <div
        class="${o6({
        "filter-handle": true,
        bypassed: e8.bypass,
        selected: t5 === this.selectedFilterIdx
      })}"
        @dblclick=${(n7) => this.onFilterHandleDoubleClick(n7, t5, e8)}
      >
        ${(r5 = M(this.runtime.spec, t5)) != null ? r5 : ""}
      </div>
    </div>`;
    }
    getFilterPositionInVisualisation(e8) {
      var n7, a3, l6, u4;
      if (!this.runtime)
        return [0, 0];
      let t5 = (a3 = (n7 = this.analyserCanvas) == null ? void 0 : n7.offsetWidth) != null ? a3 : 0, i7 = (u4 = (l6 = this.analyserCanvas) == null ? void 0 : l6.offsetHeight) != null ? u4 : 0, s5 = D(e8.frequency, 10, this.runtime.audioCtx.sampleRate / 2) * t5, r5 = i7 - (e8.gain + 15) / 30 * i7;
      return E(e8.type) || (r5 = i7 - D(e8.Q, 0.1, 18) * i7), [s5, r5];
    }
    onFilterHandleDoubleClick(e8, t5, i7) {
      e8.preventDefault(), e8.stopPropagation(), !(!this.runtime || !E(i7.type)) && (this.selectedFilterIdx = t5, this.runtime.setFilterGain(t5, 0));
    }
    startDraggingFilterHandle(e8, t5) {
      e8.target.setPointerCapture(e8.pointerId), this.dragStates = { ...this.dragStates, [t5]: e8.pointerId }, this.selectedFilterIdx = t5, e8.preventDefault();
    }
    stopDraggingFilterHandle(e8, t5) {
      this.dragStates[t5] === e8.pointerId && (e8.target.releasePointerCapture(e8.pointerId), this.dragStates = { ...this.dragStates, [t5]: null });
    }
    dragFilterHandle(e8, t5) {
      var i7, s5;
      if (this.runtime && this.dragStates[t5] === e8.pointerId) {
        let r5 = this.runtime.spec[t5].type, n7 = (s5 = (i7 = this.frequencyResponseCanvas) == null ? void 0 : i7.getBoundingClientRect()) != null ? s5 : {
          left: 0,
          top: 0,
          width: 0,
          height: 0
        }, a3 = e8.clientX - n7.left, l6 = e8.clientY - n7.top, u4 = B(
          a3 / n7.width,
          10,
          this.runtime.audioCtx.sampleRate / 2
        );
        this.runtime.setFilterFrequency(t5, u4);
        let o7 = 1 - l6 / n7.height;
        if (E(r5)) {
          let c3 = i(o7 * 30 - 15, -15, 15);
          this.runtime.setFilterGain(t5, c3);
        } else {
          let c3 = B(o7, 0.1, 18);
          this.runtime.setFilterQ(t5, c3);
        }
      }
    }
    onWheelFilterHandle(e8, t5) {
      if (!this.runtime)
        return;
      e8.preventDefault();
      const i7 = this.runtime.spec[t5], s5 = e8.deltaY < 0 ? 1 : -1, r5 = 10, n7 = this.runtime.audioCtx.sampleRate / 2, a3 = 0.1, l6 = 18;
      if (e8.shiftKey && e8.altKey) {
        const u4 = D(i7.frequency, r5, n7), o7 = 1e-3 * s5, c3 = B(i(u4 + o7, 0, 1), r5, n7);
        this.runtime.setFilterFrequency(t5, c3);
      } else if (e8.ctrlKey && e8.altKey) {
        if (x(i7.type)) {
          const u4 = 0.01 * s5, o7 = i(i7.Q + u4, a3, l6);
          this.runtime.setFilterQ(t5, o7);
        }
      } else if (e8.shiftKey) {
        const u4 = D(i7.frequency, r5, n7), o7 = 0.01 * s5, c3 = B(i(u4 + o7, 0, 1), r5, n7);
        this.runtime.setFilterFrequency(t5, c3);
      } else if (e8.ctrlKey) {
        if (x(i7.type)) {
          const u4 = D(i7.Q, a3, l6), o7 = 0.01 * s5, c3 = B(i(u4 + o7, 0, 1), a3, l6);
          this.runtime.setFilterQ(t5, c3);
        }
      } else if (e8.altKey) {
        if (E(i7.type)) {
          const u4 = 0.1 * s5, o7 = i(i7.gain + u4, -15, 15);
          this.runtime.setFilterGain(t5, o7);
        }
      } else if (E(i7.type)) {
        const u4 = 0.5 * s5, o7 = i(i7.gain + u4, -15, 15);
        this.runtime.setFilterGain(t5, o7);
      }
    }
  };
  b3.styles = [
    J,
    i2`
      :host {
        position: relative;
        display: flex;
        flex-direction: row;
        align-items: stretch;
        gap: 10px;
        min-width: 600px;
        min-height: 200px;
        padding: 20px;
        border-radius: 8px;
        overflow: visible;
        background: #202020;
        border: 1px solid #373737;
      }
      .filters {
        display: inline-grid;
        grid-auto-flow: row;
        gap: 4px;
      }
      .filters tbody,
      .filters tr {
        display: contents;
      }
      .filters thead {
        display: grid;
        grid-auto-flow: column;
        grid-template-columns: 60px 60px 50px 40px;
        align-items: center;
        gap: 4px;
      }
      .filters thead th {
        display: grid;
        place-content: center;
        height: 20px;
        border-radius: 10px;
        font-weight: var(--font-weight);
        border: 1px solid #373737;
      }
      .filters thead th.headerFilter {
        text-align: left;
        padding-left: 18px;
        border: none;
      }
      .visualisation {
        flex: 1;
        position: relative;
        border: 1px solid #373737;
      }
      .curve-probe-layer {
        position: absolute;
        inset: 0;
        pointer-events: none;
        z-index: 2;
      }
      canvas,
      svg {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
      }
      svg {
        overflow: visible;
      }
      .grid-x,
      .grid-y {
        stroke: #333;
        stroke-width: 1;
        vector-effect: non-scaling-stroke;
      }
      .filter-handle-positioner {
        position: absolute;
        top: 0;
        left: 0;
        width: 30px;
        height: 30px;
        touch-action: none;
      }
      .filter-handle {
        position: absolute;
        top: 0;
        left: 0;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background-color: #fff;
        color: black;
        transform: translate(-50%, -50%);
        display: flex;
        justify-content: center;
        align-items: center;
        user-select: none;
        cursor: grab;
        transition: background-color 0.15s ease;
      }
      .filter-handle.selected {
        background: #ffcc00;
      }
      .filter-handle.bypassed {
        background: #7d7d7d;
      }
      .curve-probe-overlay {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 2;
      }
      .curve-probe-line {
        stroke: #7d7d7d;
        stroke-width: 1;
        stroke-dasharray: 3 3;
        vector-effect: non-scaling-stroke;
      }
      .curve-probe-marker {
        position: absolute;
        width: 8px;
        height: 8px;
        transform: translate(-50%, -50%);
        border-radius: 50%;
        background: #ffcc00;
        border: 1px solid #202020;
        pointer-events: none;
        z-index: 4;
      }
      .curve-probe-anchor {
        position: absolute;
        width: 0;
        height: 0;
        transform: translate(-50%, -50%);
        pointer-events: none;
        z-index: 2;
      }
      .curve-probe-stats {
        position: absolute;
        z-index: 2;
        pointer-events: none;
        display: grid;
        gap: 2px;
        padding: 5px 8px;
        border-radius: 10px;
        background: #373737;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
        line-height: 1.3;
        white-space: nowrap;
        box-sizing: border-box;
      }
      .curve-probe-stats.placement-below {
        left: 50%;
        top: 16px;
        transform: translateX(-50%);
      }
      .curve-probe-stats.placement-above {
        left: 50%;
        bottom: 16px;
        transform: translateX(-50%);
      }
      .curve-probe-stats.placement-right {
        left: 16px;
        top: 50%;
        transform: translateY(-50%);
      }
      .curve-probe-stats.placement-left {
        right: 16px;
        top: 50%;
        transform: translateY(-50%);
      }
      .curve-probe-stats .probe-row {
        display: grid;
        grid-template-columns: 34px 1fr;
        gap: 6px;
        align-items: baseline;
      }
      .curve-probe-stats .probe-label {
        color: #7d7d7d;
        font-size: 9px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .curve-probe-stats .probe-value {
        color: white;
        text-align: right;
      }
      .curve-probe-stats .probe-db {
        color: #ffcc00;
        font-weight: var(--font-weight);
      }
      .eq-context-menu {
        position: absolute;
        z-index: 10;
        min-width: 148px;
        padding: 4px 0;
        border-radius: 10px;
        background: #373737;
        border: 1px solid #373737;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
        pointer-events: auto;
      }
      .eq-context-menu-item {
        padding: 7px 12px;
        font-family: var(--font-stack);
        font-size: var(--font-size);
        font-weight: var(--font-weight);
        color: #7d7d7d;
        cursor: default;
        user-select: none;
      }
      .eq-context-menu-item strong {
        color: white;
        font-weight: var(--font-weight);
      }
    `
  ];
  v3([
    n5({ attribute: false })
  ], b3.prototype, "runtime", 2);
  v3([
    n5()
  ], b3.prototype, "view", 2);
  v3([
    t3()
  ], b3.prototype, "analyser", 2);
  v3([
    t3()
  ], b3.prototype, "frequencyResponse", 2);
  v3([
    t3()
  ], b3.prototype, "gridXs", 2);
  v3([
    t3()
  ], b3.prototype, "dragStates", 2);
  v3([
    t3()
  ], b3.prototype, "selectedFilterIdx", 2);
  v3([
    t3()
  ], b3.prototype, "dragSourceIdx", 2);
  v3([
    t3()
  ], b3.prototype, "dragOverIdx", 2);
  v3([
    t3()
  ], b3.prototype, "curveProbe", 2);
  v3([
    t3()
  ], b3.prototype, "curveContextMenu", 2);
  v3([
    i5(".analyser")
  ], b3.prototype, "analyserCanvas", 2);
  v3([
    i5(".frequencyResponse")
  ], b3.prototype, "frequencyResponseCanvas", 2);
  b3 = v3([
    e4("weq8-ui")
  ], b3);

  // src/secret_pond/web/frontend/graph_eq_inline.js
  var MAX_SECRET_POND_EQ_POINTS = 6;
  var SUPPORTED_SECRET_POND_TYPES = Object.freeze({
    low_shelf: "lowshelf12",
    bell: "peaking12",
    high_shelf: "highshelf12"
  });
  var WEQ8C_TO_SECRET_POND_TYPES = Object.freeze({
    lowshelf12: "low_shelf",
    lowshelf24: "low_shelf",
    peaking12: "bell",
    peaking24: "bell",
    highshelf12: "high_shelf",
    highshelf24: "high_shelf"
  });
  var NOOP_FILTER = Object.freeze({
    type: "noop",
    frequency: 350,
    gain: 0,
    Q: 1,
    bypass: false
  });
  var clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value)));
  var normalizeSecretPondPoint = (point, index = 0) => {
    const type = WEQ8C_TO_SECRET_POND_TYPES[point?.type] || point?.type || "bell";
    return {
      id: String(point?.id || `point-${index + 1}`),
      type,
      frequency_hz: Math.round(clamp(point?.frequency_hz ?? point?.frequency ?? 1e3, 20, 2e4)),
      gain_db: Number(clamp(point?.gain_db ?? point?.gain ?? 0, -18, 18).toFixed(1)),
      q: Number(clamp(point?.q ?? point?.Q ?? 1, 0.1, 18).toFixed(2))
    };
  };
  var toSecretPondEqPoints = (filters = []) => filters.map((filter, index) => normalizeSecretPondPoint(filter, index)).filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type)).slice(0, MAX_SECRET_POND_EQ_POINTS);
  var fromSecretPondEqPoints = (points = []) => points.map((point, index) => normalizeSecretPondPoint(point, index)).filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type)).slice(0, MAX_SECRET_POND_EQ_POINTS).map((point) => ({
    id: point.id,
    type: SUPPORTED_SECRET_POND_TYPES[point.type],
    frequency: point.frequency_hz,
    gain: point.gain_db,
    Q: point.q,
    bypass: false
  }));
  var toWeq8cSpec = (points = []) => {
    const filters = fromSecretPondEqPoints(points);
    while (filters.length < 8) filters.push({ ...NOOP_FILTER });
    return filters.slice(0, 8);
  };
  var createAudioContext = () => {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    return AudioContextClass ? new AudioContextClass() : null;
  };
  var createRuntime = (points = [], audioContext = createAudioContext()) => {
    if (!audioContext) return null;
    return new Q2(audioContext, toWeq8cSpec(points));
  };
  var syncRuntime = (runtime, points = []) => {
    if (!runtime?.spec) return null;
    const nextSpec = toWeq8cSpec(points);
    nextSpec.forEach((filter, index) => {
      if (runtime.spec[index]?.type !== filter.type) runtime.setFilterType(index, filter.type);
      if (runtime.spec[index]?.frequency !== filter.frequency) runtime.setFilterFrequency(index, filter.frequency);
      if (runtime.spec[index]?.gain !== filter.gain) runtime.setFilterGain(index, filter.gain);
      if (runtime.spec[index]?.Q !== filter.Q) runtime.setFilterQ(index, filter.Q);
      if (runtime.spec[index]?.bypass !== filter.bypass) runtime.toggleBypass(index, filter.bypass);
    });
    return runtime;
  };
  window.secretPondGraphEq = Object.freeze({
    MAX_SECRET_POND_EQ_POINTS,
    SUPPORTED_SECRET_POND_TYPES,
    createRuntime,
    syncRuntime,
    toWeq8cSpec,
    toSecretPondEqPoints,
    fromSecretPondEqPoints
  });
})();
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
@lit/reactive-element/decorators/custom-element.js:
@lit/reactive-element/decorators/property.js:
@lit/reactive-element/decorators/state.js:
@lit/reactive-element/decorators/base.js:
@lit/reactive-element/decorators/event-options.js:
@lit/reactive-element/decorators/query.js:
@lit/reactive-element/decorators/query-all.js:
@lit/reactive-element/decorators/query-async.js:
@lit/reactive-element/decorators/query-assigned-nodes.js:
lit-html/directive.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directives/class-map.js:
  (**
   * @license
   * Copyright 2018 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
