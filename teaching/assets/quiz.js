/* ============================================================
   teach workspace — reusable quiz widget
   Usage:
     <div class="quiz" data-quiz>
       <p class="quiz-q">题目</p>
       <button class="quiz-opt" data-correct="true">选项A</button>
       <button class="quiz-opt" data-correct="false">选项B</button>
       <p class="quiz-note"></p>
     </div>
   Clicking an option locks the question, marks correct/wrong,
   and writes feedback into the sibling .quiz-note.
   Score is tallied per-quiz into a .quiz-score element (optional).
   ============================================================ */

(function () {
  function initQuiz(quiz) {
    var options = quiz.querySelectorAll('.quiz-opt');
    var note = quiz.querySelector('.quiz-note');
    var scoreEl = quiz.querySelector('.quiz-score');
    var correctCount = 0;
    var answered = false;

    options.forEach(function (opt) {
      opt.addEventListener('click', function () {
        if (answered) return;
        answered = true;
        var isCorrect = opt.getAttribute('data-correct') === 'true';
        options.forEach(function (o) { o.classList.add('done'); });
        opt.classList.add('selected');
        opt.classList.add(isCorrect ? 'correct' : 'wrong');
        if (isCorrect) {
          correctCount += 1;
          if (note) note.textContent = '✓ 正确';
        } else {
          if (note) note.textContent = '✗ 不对——看下面的解析';
        }
        if (scoreEl) {
          scoreEl.textContent = '本组得分：' + correctCount + ' / ' + options.length;
        }
      });
    });
  }

  document.querySelectorAll('[data-quiz]').forEach(initQuiz);
})();
