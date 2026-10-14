/* A project's full skill table, for managers; see personnel/project_detail.html.
 *
 * Rows and who holds each skill come from json_script blocks. Filtering only
 * hides rows: what is submitted is generated from the row state, so a ticked
 * skill that is filtered out of view is still saved. The server replaces the
 * project's requirements with the submitted set.
 */
document.addEventListener('alpine:init', function() {
  var DEFAULT_LEVEL = 3;
  var OPEN_KEY = 'projectSkills.openDomains';   // which domains are expanded, across saves
  var MISSING = 'Not in taxonomy';

  Alpine.data('projectSkills', function() {
    var saving = false;
    var skillUrl = '';   // with a SKILL_ID placeholder; read in init(), where $el is the root

    return {
      rows: [],
      groups: [],      // [{name, rows}] in display order; rows are shared with this.rows
      domains: [],
      holders: {},     // skill id -> [[person name, level], ...]
      // The requirements are what a project is; the full taxonomy is the
      // picker you switch to when adding one.
      view: 'required', // 'required' | 'all'
      open: {},        // domain name -> true when expanded
      query: '',
      domain: '',

      init: function() {
        var self = this;
        skillUrl = this.$el.dataset.skillUrl;
        this.holders = JSON.parse(document.getElementById('project-skill-holders').textContent);
        this.rows = JSON.parse(document.getElementById('project-skill-rows').textContent).map(function(r) {
          r.index = searchIndex.build(r.name + ' ' + r.id + ' ' + r.domain, [r.category].concat(r.tags));
          return r;
        });
        var byName = {};
        this.rows.forEach(function(r) {
          if (!byName[r.domain]) {
            byName[r.domain] = {name: r.domain, rows: []};
            self.groups.push(byName[r.domain]);
            self.domains.push(r.domain);
          }
          byName[r.domain].rows.push(r);
        });
        try {
          (JSON.parse(localStorage.getItem(OPEN_KEY)) || []).forEach(function(name) { self.open[name] = true; });
        } catch (e) { /* storage unavailable: start collapsed */ }
        if (byName[MISSING]) this.open[MISSING] = true;   // these need attention
        window.addEventListener('beforeunload', function(e) {
          if (!saving && self.changes.any) { e.preventDefault(); e.returnValue = ''; }
        });
      },

      matches: function(row) {
        if (this.view === 'required' && !row.required) return false;
        if (this.domain && row.domain !== this.domain) return false;
        return searchIndex.matches(row.index, searchIndex.terms(this.query));
      },
      // Tags or category that explain a search match the visible text doesn't.
      reasons: function(row) {
        return this.query.trim() ? searchIndex.reasons(row.index, searchIndex.terms(this.query)) : [];
      },
      // While searching or filtering, every group with matches is shown open,
      // so a match is never hidden inside a collapsed domain.
      get filtering() {
        return this.view === 'required' || !!this.domain || !!this.query.trim();
      },
      isOpen: function(group) {
        return this.filtering || !!this.open[group.name];
      },
      toggle: function(group) {
        this.open[group.name] = !this.open[group.name];
        this.saveOpen();
      },
      setAllOpen: function(value) {
        var self = this;
        this.groups.forEach(function(g) { self.open[g.name] = value; });
        this.saveOpen();
      },
      saveOpen: function() {
        var open = this.open;
        try {
          localStorage.setItem(OPEN_KEY, JSON.stringify(Object.keys(open).filter(function(k) { return open[k]; })));
        } catch (e) { /* not remembered; harmless */ }
      },

      groupVisible: function(group) {
        var self = this;
        return group.rows.some(function(r) { return self.matches(r); });
      },
      groupSummary: function(group) {
        var self = this;
        var required = group.rows.filter(function(r) { return r.required; });
        var gaps = required.filter(function(r) { return !self.qualified(r).length; }).length;
        var text = required.length + ' of ' + group.rows.length + ' required';
        return gaps ? text + ' · ' + gaps + (gaps === 1 ? ' gap' : ' gaps') : text;
      },
      get anyVisible() {
        var self = this;
        return this.groups.some(function(g) { return self.groupVisible(g); });
      },

      qualified: function(row) {
        return (this.holders[row.id] || [])
          .filter(function(h) { return h[1] >= row.level; })
          .map(function(h) { return h[0]; });
      },
      close: function(row) {
        return (this.holders[row.id] || [])
          .filter(function(h) { return h[1] === row.level - 1; })
          .map(function(h) { return h[0]; });
      },

      status: function(row) {
        var n = this.qualified(row).length;
        if (n) return {text: n + ' qualified', cls: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'};
        if (this.close(row).length) return {text: 'Close', cls: 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'};
        return {text: 'Gap', cls: 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400'};
      },

      skillUrl: function(row) { return skillUrl.replace('SKILL_ID', encodeURIComponent(row.id)); },

      // Clicking a row opens the skill. A new tab, because the table holds
      // unsaved requirement and level edits that navigating away would put
      // behind a "leave site?" prompt.
      openSkill: function(row, e) {
        if (row.status === 'missing') return;        // no taxonomy page to open
        // The cells people click to edit, and the name's own link, handle
        // themselves.
        if (e.target.closest('input, select, a, button, label, option')) return;
        if (String(window.getSelection() || '')) return;   // selecting text
        window.open(this.skillUrl(row), '_blank', 'noopener');
      },

      get coverage() {
        var self = this;
        var required = this.rows.filter(function(r) { return r.required; });
        var covered = required.filter(function(r) { return self.qualified(r).length > 0; }).length;
        return {
          required: required.length, covered: covered,
          pct: required.length ? Math.round(100 * covered / required.length) : null,
        };
      },

      // Differences from what is saved, for the change bar.
      get changes() {
        var c = {added: 0, removed: 0, levels: 0};
        this.rows.forEach(function(r) {
          var saved = r.saved_level !== null;
          if (r.required && !saved) c.added++;
          else if (!r.required && saved) c.removed++;
          else if (r.required && r.level !== r.saved_level) c.levels++;
        });
        c.any = c.added + c.removed + c.levels > 0;
        c.summary = [
          c.added && c.added + ' added',
          c.removed && c.removed + ' removed',
          c.levels && c.levels + (c.levels === 1 ? ' level' : ' levels') + ' changed',
        ].filter(Boolean).join(' · ');
        return c;
      },

      setLevel: function(row, value) {
        row.level = Number(value);
        row.required = true;    // picking a level only makes sense for a required skill
      },

      discard: function() {
        this.rows.forEach(function(r) {
          r.required = r.saved_level !== null;
          r.level = r.required ? r.saved_level : DEFAULT_LEVEL;
        });
      },

      onSubmit: function() { saving = true; },
    };
  });
});
