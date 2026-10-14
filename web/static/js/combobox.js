/* Searchable picker layered over a native <select>.
 *
 *   <div x-data="combobox" class="relative">
 *     <select name="...">...</select>
 *     {% include "core/partials/combobox.html" %}
 *   </div>
 *
 * The <select> stays in the form as the submitted field (and is what users
 * without JS get); this component hides it, reads its options and optgroups,
 * and writes the chosen value back to it. Search matches every word typed,
 * in any order, against the option text, its group label and its value, plus
 * any extra terms in the option's data-search="a|b|c" (e.g. a skill's tags).
 */

/* Word matching for skill searches.
 * Hyphens and underscores count as spaces, so "reverse-engineering" in a tag
 * matches a query of "reverse engineering" and vice versa. `extras` are terms
 * that match but aren't displayed, so reasons() reports which ones explained
 * a result the visible text doesn't. */
window.searchIndex = (function() {
  function normalize(text) { return String(text || '').toLowerCase().replace(/[-_]+/g, ' '); }
  return {
    terms: function(query) { return normalize(query).split(/\s+/).filter(Boolean); },
    build: function(visible, extras) {
      var ex = (extras || []).map(normalize).filter(Boolean);
      return {visible: normalize(visible), extras: ex, all: normalize(visible) + ' ' + ex.join(' ')};
    },
    matches: function(index, terms) {
      return terms.every(function(t) { return index.all.indexOf(t) !== -1; });
    },
    reasons: function(index, terms) {
      var out = [];
      terms.forEach(function(t) {
        if (index.visible.indexOf(t) !== -1) return;
        index.extras.forEach(function(e) {
          if (e.indexOf(t) !== -1 && out.indexOf(e) === -1) out.push(e);
        });
      });
      return out.slice(0, 2);
    },
  };
})();

document.addEventListener('alpine:init', function() {
  Alpine.data('combobox', function() {
    // Captured in init(): inside methods, this.$el is whichever element's
    // handler is running, not the component root.
    var root, select, input;

    return {
      options: [],     // {value, label, group, index}
      results: [],     // {opt, heading, reasons} for the current query
      terms: [],
      value: '',
      query: '',
      placeholder: '',
      clearable: false,
      open: false,
      active: -1,      // index into results
      invalid: false,
      ready: false,
      uid: '',

      init: function() {
        var self = this;
        root = this.$el;
        select = root.querySelector('select');
        input = root.querySelector('input[role="combobox"]');
        this.uid = 'cb-' + Math.random().toString(36).slice(2, 10);

        Array.prototype.forEach.call(select.options, function(o) {
          var label = o.text.trim();
          if (o.value === '') {
            self.clearable = true;
            self.placeholder = self.placeholder || label;
            return;
          }
          var group = o.parentElement.tagName === 'OPTGROUP' ? o.parentElement.label : '';
          var extras = o.dataset.search ? o.dataset.search.split('|') : [];
          self.options.push({
            value: o.value, label: label, group: group,
            index: searchIndex.build(label + ' ' + group + ' ' + o.value, extras),
          });
        });
        if (input.placeholder) this.placeholder = input.placeholder;

        // The visible input takes over the select's id so <label for> keeps working.
        if (select.id) { input.id = select.id; select.removeAttribute('id'); }
        select.classList.add('sr-only');
        select.tabIndex = -1;
        select.setAttribute('aria-hidden', 'true');
        select.addEventListener('invalid', function(e) {
          e.preventDefault();
          self.invalid = true;
          input.focus();
        });

        this.value = select.value;
        this.reset();
        this.ready = true;
      },

      current: function() {
        var v = this.value;
        return this.options.find(function(o) { return o.value === v; }) || null;
      },

      // Show the current selection as the input's text.
      reset: function() {
        var c = this.current();
        this.query = c ? c.label : '';
      },

      refresh: function() {
        var terms = searchIndex.terms(this.query);
        var prev = null;
        this.terms = terms;
        this.results = this.options
          .filter(function(o) { return searchIndex.matches(o.index, terms); })
          .map(function(o) {
            var row = {opt: o, heading: o.group !== prev ? o.group : '', reasons: searchIndex.reasons(o.index, terms)};
            prev = o.group;
            return row;
          });
      },

      openList: function() {
        if (this.open) return;
        var v = this.value;
        this.query = '';
        this.refresh();
        this.active = this.results.findIndex(function(r) { return r.opt.value === v; });
        if (this.active === -1 && this.results.length) this.active = 0;
        this.open = true;
        this.scrollToActive();
      },

      close: function() {
        if (!this.open) return;
        this.open = false;
        this.reset();
      },

      onInput: function(e) {
        // First keystroke after a choice replaces the shown label instead of appending to it.
        this.query = this.open ? e.target.value : (e.data || '');
        this.open = true;
        this.invalid = false;
        this.refresh();
        this.active = this.results.length ? 0 : -1;
        this.scrollToActive();
      },

      move: function(step) {
        if (!this.open) { this.openList(); return; }
        if (!this.results.length) return;
        var n = this.results.length;
        this.active = (this.active + step + n) % n;
        this.scrollToActive();
      },

      onEnter: function(e) {
        if (!this.open) return;
        e.preventDefault();
        if (this.active >= 0) this.choose(this.results[this.active].opt);
      },

      onEscape: function(e) {
        // Keep the global Escape handler from closing the surrounding modal.
        if (!this.open) return;
        e.stopPropagation();
        this.close();
      },

      onFocusOut: function(e) {
        if (!root.contains(e.relatedTarget)) this.close();
      },

      choose: function(opt) {
        this.setValue(opt.value);
        this.open = false;
        this.reset();
      },

      clear: function() {
        this.setValue('');
        input.focus();
        this.openList();
      },

      setValue: function(v) {
        this.value = v;
        this.invalid = false;
        select.value = v;
        select.dispatchEvent(new Event('change', {bubbles: true}));
      },

      scrollToActive: function() {
        var id = this.uid + '-' + this.active;
        this.$nextTick(function() {
          var el = document.getElementById(id);
          if (el) el.scrollIntoView({block: 'nearest'});
        });
      },

      // Split a label into [{text, hit}] runs so matched terms can be emphasised.
      parts: function(text) {
        var lower = text.toLowerCase().replace(/[-_]/g, ' ');   // per character, to keep positions
        if (!this.terms.length || lower.length !== text.length) return [{text: text, hit: false}];
        var hit = new Array(text.length).fill(false);
        this.terms.forEach(function(t) {
          for (var i = lower.indexOf(t); i !== -1; i = lower.indexOf(t, i + t.length)) {
            for (var j = i; j < i + t.length; j++) hit[j] = true;
          }
        });
        var out = [];
        for (var k = 0; k < text.length; k++) {
          var last = out[out.length - 1];
          if (last && last.hit === hit[k]) last.text += text[k];
          else out.push({text: text[k], hit: hit[k]});
        }
        return out;
      },
    };
  });
});
